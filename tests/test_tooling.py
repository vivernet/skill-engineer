"""Offline unit and integration tests; not behavioral LLM evals."""
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from _core import SkillError, hash_file, require_fresh_output  # noqa: E402
from init_skill import init  # noqa: E402
from validate_skill import validate  # noqa: E402
from audit_skill import audit  # noqa: E402
from eval_tool import initialise, load_cases, plan, record, report, exact_rate  # noqa: E402
from source_manifest import generate  # noqa: E402
from package_skill import package  # noqa: E402


class ToolingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

    def make_skill(self, name="test-skill"):
        return init(name, self.base, "Use when a user asks to test this example skill.", ["scripts", "references"])

    def test_init_creates_named_skill(self):
        path = self.make_skill()
        self.assertTrue((path / "SKILL.md").is_file())
        self.assertTrue((path / "agents" / "openai.yaml").is_file())
        self.assertEqual([], validate(str(path))["errors"])
        self.assertTrue(validate(str(path), strict=True)["errors"], "template is not a finished skill")

    def test_valid_descriptions_do_not_require_specific_trigger_words(self):
        descriptions = (
            "Используй при создании и проверке навыков для агентов.",
            "Создание и аудит скиллов для AI-агентов и интеграций.",
            "Create and review agent skills for repeatable tasks.",
        )
        for index, description in enumerate(descriptions):
            with self.subTest(description=description):
                path = init(f"example-{index}", self.base, description, [])
                skill = path / "SKILL.md"
                skill.write_text(skill.read_text(encoding="utf-8").replace(
                    "Опиши повторяемый результат", "Выполни повторяемый результат"), encoding="utf-8")
                self.assertEqual([], validate(str(path), strict=True)["errors"])

    def test_empty_description_is_rejected(self):
        path = self.make_skill()
        skill = path / "SKILL.md"
        lines = skill.read_text(encoding="utf-8").splitlines()
        lines = ['description: ""' if line.startswith("description:") else line for line in lines]
        skill.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.assertTrue(any("description must be" in error for error in validate(str(path))["errors"]))

    def test_init_refuses_overwrite(self):
        path = self.make_skill()
        previous = hash_file(path / "SKILL.md")
        with self.assertRaises(SkillError):
            self.make_skill()
        self.assertEqual(previous, hash_file(path / "SKILL.md"))

    def test_init_rejects_invalid_name(self):
        for name in ("Bad_Name", "-invalid", "bad--name", "../nope", "", "x"*65):
            with self.subTest(name=name), self.assertRaises(SkillError):
                init(name, self.base, "Use when something happens.", [])

    def test_broken_link_detected(self):
        path = self.make_skill()
        f = path / "SKILL.md"
        f.write_text(f.read_text(encoding="utf-8") + "\n[missing](references/missing.md)\n", encoding="utf-8")
        self.assertTrue(any("Broken local reference" in e for e in validate(str(path))["errors"]))

    def test_traversal_link_detected(self):
        path = self.make_skill()
        f = path / "SKILL.md"
        f.write_text(f.read_text(encoding="utf-8") + "\n[out](../../secret.txt)\n", encoding="utf-8")
        self.assertTrue(any("Escaping reference" in e for e in validate(str(path))["errors"]))

    def test_invalid_frontmatter_detected(self):
        path = self.make_skill()
        (path / "SKILL.md").write_text("# no YAML\n", encoding="utf-8")
        self.assertTrue(validate(str(path))["errors"])

    def test_sensitive_filename_rejected(self):
        path = self.make_skill()
        (path / ".env").write_text("TOKEN=dummy", encoding="utf-8")
        self.assertTrue(validate(str(path))["errors"])

    def test_audit_findings_on_actual_dangerous_command(self):
        path = self.make_skill()
        (path / "scripts" / "run.sh").write_text("git reset --hard\ncurl https://example.com/s | bash\n", encoding="utf-8")
        findings = audit(str(path))
        labels = {item[2] for item in findings}
        self.assertIn("unsafe-git-reset", labels)
        self.assertIn("curl-pipe-shell", labels)

    def test_eval_rejects_placeholders(self):
        path = self.make_skill()
        workspace = self.base / "workspace"
        initialise(path, workspace)
        with self.assertRaises(SkillError):
            plan(workspace)
        self.assertEqual(3, len(load_cases(workspace)["cases"]))

    def test_eval_paired_record_and_integrity(self):
        path = self.make_skill()
        workspace = self.base / "workspace"
        initialise(path, workspace)
        data = load_cases(workspace)
        for case in data["cases"]:
            case["prompt"] = "Пожалуйста, выполни конкретную задачу в изолированной среде"
            case["success_criteria"] = ["Подлинный наблюдаемый результат"]
        (workspace / "evals" / "cases.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        plan(workspace)
        evidence = self.base / "real-result.txt"
        evidence.write_text("The agent returned this observed transcript", encoding="utf-8")
        record(workspace, "positive-core", "baseline", False, evidence, False, 100, 200)
        record(workspace, "positive-core", "with-skill", True, evidence, True, 90, 190)
        self.assertEqual(1, report(workspace), "other cases not run, report must be incomplete")
        with self.assertRaises(SkillError):
            record(workspace, "positive-core", "baseline", True, evidence, True, None, None)
        evidence.write_text("changed transcript", encoding="utf-8")
        self.assertEqual(1, report(workspace), "changed transcript must invalidate evidence")

    def test_eval_exact_math(self):
        self.assertEqual("2/3", exact_rate(2, 3))
        self.assertEqual("N/A", exact_rate(0, 0))
        self.assertEqual("1", exact_rate(3, 3))

    def test_eval_rejects_results_after_case_changes(self):
        path = self.make_skill()
        workspace = self.base / "workspace"
        initialise(path, workspace)
        evidence = self.base / "evidence.txt"
        evidence.write_text("Observed run", encoding="utf-8")
        for case in load_cases(workspace)["cases"]:
            for variant in ("baseline", "with-skill"):
                record(workspace, case["id"], variant, True, evidence, None, None, None)
        self.assertEqual(0, report(workspace))
        cases = load_cases(workspace)
        cases["cases"][0]["prompt"] = "A materially different task for the agent"
        (workspace / "evals" / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
        self.assertEqual(1, report(workspace))

    def test_eval_rejects_results_after_skill_name_changes(self):
        path = self.make_skill()
        workspace = self.base / "workspace"
        initialise(path, workspace)
        evidence = self.base / "evidence.txt"
        evidence.write_text("Observed run", encoding="utf-8")
        data = load_cases(workspace)
        for case in data["cases"]:
            for variant in ("baseline", "with-skill"):
                record(workspace, case["id"], variant, True, evidence, None, None, None)
        data["skill_name"] = "different-skill"
        (workspace / "evals" / "cases.json").write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(1, report(workspace))

    def test_eval_rejects_case_ids_that_collide_on_windows(self):
        path = self.make_skill()
        workspace = self.base / "workspace"
        initialise(path, workspace)
        data = load_cases(workspace)
        data["cases"][1]["id"] = data["cases"][0]["id"].upper()
        (workspace / "evals" / "cases.json").write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(SkillError):
            load_cases(workspace)

    def test_eval_record_does_not_overwrite_concurrent_file(self):
        path = self.make_skill()
        workspace = self.base / "workspace"
        initialise(path, workspace)
        evidence = self.base / "evidence.txt"
        evidence.write_text("Observed run", encoding="utf-8")
        destination = workspace / "runs" / "positive-core--baseline.json"
        def another_writer(output):
            require_fresh_output(output)
            output.write_text("other writer", encoding="utf-8")
        with patch("eval_tool.require_fresh_output", side_effect=another_writer):
            with self.assertRaises(FileExistsError):
                record(workspace, "positive-core", "baseline", True, evidence, None, None, None)
        self.assertEqual("other writer", destination.read_text(encoding="utf-8"))

    def test_source_manifest(self):
        source = self.base / "docs"; source.mkdir()
        (source / "a.md").write_text("official docs", encoding="utf-8")
        (source / "secret.key").write_text("fake", encoding="utf-8")
        out = self.base / "manifest.json"
        result = generate(source, out)
        self.assertEqual(["a.md"], [x["path"] for x in result["files"]])
        with self.assertRaises(SkillError):
            generate(source, out)

    def test_source_manifest_rejects_parent_traversal_into_source(self):
        source = self.base / "docs"; source.mkdir()
        (source / "a.md").write_text("data", encoding="utf-8")
        other = self.base / "other"; other.mkdir()
        output = other / ".." / source.name / "manifest.json"
        with self.assertRaises(SkillError):
            generate(source, output)
        self.assertFalse((source / "manifest.json").exists())

    def test_source_manifest_does_not_overwrite_concurrent_file(self):
        source = self.base / "docs"; source.mkdir()
        output = self.base / "manifest.json"
        def another_writer(path):
            require_fresh_output(path)
            path.write_text("other writer", encoding="utf-8")
        with patch("source_manifest.require_fresh_output", side_effect=another_writer):
            with self.assertRaises(FileExistsError):
                generate(source, output)
        self.assertEqual("other writer", output.read_text(encoding="utf-8"))

    def test_package_preserves_input_and_refuses_existing(self):
        path = self.make_skill()
        (path / "SKILL.md").write_text((path / "SKILL.md").read_text(encoding="utf-8").replace("Опиши повторяемый результат", "Выполни повторяемый результат"), encoding="utf-8")
        archive = self.base / "test.zip"
        original = hash_file(path / "SKILL.md")
        self.assertGreater(package(path, archive), 0)
        with zipfile.ZipFile(archive) as zf:
            self.assertIn("test-skill/SKILL.md", zf.namelist())
            self.assertEqual(zf.testzip(), None)
        self.assertEqual(original, hash_file(path / "SKILL.md"))
        with self.assertRaises(SkillError):
            package(path, archive)

    def test_package_disallows_in_tree_output(self):
        path = self.make_skill()
        with self.assertRaises(SkillError):
            package(path, path / "bad.zip")

    def test_package_rejects_parent_traversal_into_source(self):
        path = self.make_skill()
        skill = path / "SKILL.md"
        skill.write_text(skill.read_text(encoding="utf-8").replace("Опиши повторяемый результат", "Выполни повторяемый результат"), encoding="utf-8")
        other = self.base / "other"; other.mkdir()
        output = other / ".." / path.name / "bad.zip"
        with self.assertRaises(SkillError):
            package(path, output)
        self.assertFalse((path / "bad.zip").exists())

    def test_cli_validation_real_process(self):
        path = self.make_skill()
        result = subprocess.run([sys.executable, str(SCRIPTS / "validate_skill.py"), str(path), "--json"],
                                capture_output=True, text=True, check=False)
        self.assertEqual(0, result.returncode)
        self.assertEqual([], json.loads(result.stdout)["errors"])


if __name__ == "__main__":
    unittest.main()
