"""Prepare paired agent evals, record externally observed results, report exact ratios."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from fractions import Fraction
from pathlib import Path
from _core import SkillError, check_root, hash_file, read_frontmatter, require_fresh_output

CASE_TYPES = {"behavior", "trigger", "adversarial", "integration", "regression"}
VARIANTS = ("baseline", "with-skill")


def case_hash(skill_name: str, case: dict) -> str:
    data = json.dumps({"skill_name": skill_name, "case": case}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def load_cases(workspace: Path) -> dict:
    try:
        value = json.loads((workspace / "evals" / "cases.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SkillError(f"Invalid evals/cases.json: {exc}") from exc
    if (value.get("schema_version") != 1 or not isinstance(value.get("cases"), list)
            or not isinstance(value.get("skill_name"), str) or not value["skill_name"].strip()):
        raise SkillError("Expected schema_version 1, skill_name and cases[]")
    seen = set()
    for case in value["cases"]:
        if (not isinstance(case, dict) or not isinstance(case.get("id"), str)
                or not case["id"].replace("-", "").replace("_", "").isalnum()
                or not isinstance(case.get("prompt"), str) or len(case["prompt"].strip()) < 8
                or not isinstance(case.get("should_trigger"), bool)
                or case.get("type") not in CASE_TYPES
                or not isinstance(case.get("success_criteria"), list)
                or not case["success_criteria"]):
            raise SkillError(f"Invalid case: {case!r}")
        if case["id"].casefold() in seen:
            raise SkillError(f"Duplicate case: {case['id']}")
        seen.add(case["id"].casefold())
    return value


def initialise(skill: Path, workspace: Path):
    skill = check_root(str(skill))
    values, _, _ = read_frontmatter(skill / "SKILL.md")
    workspace = workspace.expanduser().absolute()
    require_fresh_output(workspace)
    cases = {"schema_version": 1, "skill_name": values.get("name", skill.name), "cases": [
        {"id": "positive-core", "type": "behavior", "should_trigger": True,
         "prompt": "Замените это предложение реальной задачей, требующей навык",
         "success_criteria": ["Заменить конкретным измеримым условием"]},
        {"id": "negative-nearby", "type": "trigger", "should_trigger": False,
         "prompt": "Замените это предложение близкой задачей, не требующей навык",
         "success_criteria": ["Навык не должен активироваться"]},
        {"id": "adversarial", "type": "adversarial", "should_trigger": True,
         "prompt": "Замените это предложение реальным сценарием давления и ошибочных инструкций",
         "success_criteria": ["Соблюдён инвариант безопасности"]}
    ]}
    workspace.mkdir()
    (workspace / "evals").mkdir()
    (workspace / "runs").mkdir()
    (workspace / "evals" / "cases.json").write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Created workspace: {workspace}\nEdit evals/cases.json BEFORE executing and recording any runs")


def plan(workspace: Path):
    data = load_cases(workspace)
    for case in data["cases"]:
        if "Замените" in case["prompt"] or any("Заменить" in x for x in case["success_criteria"]):
            raise SkillError(f"Replace placeholder test prompts: {case['id']}")
    print(f"Skill: {data['skill_name']}\nPaired tasks (not executed):")
    for case in data["cases"]:
        print(f"\n[{case['id']}] should_trigger={case['should_trigger']} type={case['type']}")
        print(f"User prompt: {case['prompt']}")
        print("Criteria: " + "; ".join(case["success_criteria"]))
        print("1. BASELINE: isolated agent without this skill (or previous snapshot).")
        print("2. WITH-SKILL: same agent/model/tools/input, this skill enabled.")
        print("Capture actual transcript/output separately; record only actual outcomes.")


def record(workspace: Path, case_id: str, variant: str, passed: bool,
           evidence: Path, triggered: bool | None, tokens: int | None, duration_ms: int | None):
    cases = load_cases(workspace)
    case = next((c for c in cases["cases"] if c["id"] == case_id), None)
    if variant not in VARIANTS or case is None:
        raise SkillError("Invalid --case or --variant")
    evidence = evidence.expanduser().absolute()
    if not evidence.is_file() or evidence.is_symlink() or evidence.stat().st_size == 0:
        raise SkillError("--evidence must be an existing nonempty regular file of an actual run")
    if tokens is not None and tokens < 0 or duration_ms is not None and duration_ms < 0:
        raise SkillError("tokens and duration-ms must be nonnegative")
    destination = workspace / "runs" / f"{case_id}--{variant}.json"
    require_fresh_output(destination)
    payload = {"case": case_id, "case_sha256": case_hash(cases["skill_name"], case), "variant": variant, "passed": passed,
               "triggered": triggered, "evidence_file": str(evidence),
               "evidence_sha256": hash_file(evidence), "tokens": tokens, "duration_ms": duration_ms,
               "verification": "externally_observed_not_independently_attested"}
    with destination.open("x", encoding="utf-8") as sink:
        sink.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(f"Recorded external result: {destination} (not verified agent execution)")


def exact_rate(numerator: int, denominator: int):
    return str(Fraction(numerator, denominator)) if denominator else "N/A"


def report(workspace: Path):
    suite = load_cases(workspace)
    cases = suite["cases"]
    counts = {key: {"passed": 0, "recorded": 0} for key in VARIANTS}
    tp = fp = fn = tn = 0
    complete = 0
    telemetry = {key: {"tokens": [], "duration_ms": []} for key in VARIANTS}
    trigger_observed = 0
    for case in cases:
        runs = {}
        for variant in VARIANTS:
            record_file = workspace / "runs" / f"{case['id']}--{variant}.json"
            if not record_file.is_file():
                print(f"NOT RUN: {case['id']} / {variant}")
                continue
            try:
                result = json.loads(record_file.read_text(encoding="utf-8"))
                if (result.get("case") != case["id"] or result.get("variant") != variant
                        or result.get("case_sha256") != case_hash(suite["skill_name"], case)):
                    raise SkillError("Case changed, record identity mismatch, or legacy record without case hash")
                evidence = Path(result["evidence_file"])
                if (evidence.is_symlink() or not evidence.is_file()
                        or hash_file(evidence) != result["evidence_sha256"]):
                    raise SkillError("Evidence missing/changed")
                if not isinstance(result.get("passed"), bool):
                    raise SkillError("Nonboolean passed value")
            except (KeyError, OSError, json.JSONDecodeError, SkillError) as exc:
                print(f"INVALID EVIDENCE: {record_file}: {exc}")
                continue
            runs[variant] = result
            counts[variant]["recorded"] += 1
            counts[variant]["passed"] += int(result["passed"])
            for field in ("tokens", "duration_ms"):
                if isinstance(result.get(field), int) and result[field] >= 0:
                    telemetry[variant][field].append(result[field])
            if variant == "with-skill" and isinstance(result.get("triggered"), bool):
                trigger_observed += 1
                actual = result["triggered"]
                expected = case["should_trigger"]
                if expected and actual: tp += 1
                elif not expected and actual: fp += 1
                elif expected and not actual: fn += 1
                else: tn += 1
        if len(runs) == 2:
            complete += 1
            print(f"PAIRED: {case['id']}: baseline={runs['baseline']['passed']}, with-skill={runs['with-skill']['passed']}")
    print("\nBehavioral outcomes are externally graded; not proof of execution:")
    for variant in VARIANTS:
        count = counts[variant]
        print(f"{variant}: {count['passed']}/{count['recorded']} = {exact_rate(count['passed'], count['recorded'])}")
    print(f"Paired complete: {complete}/{len(cases)}")
    print(f"Trigger precision: {tp}/{tp+fp} = {exact_rate(tp,tp+fp)}")
    print(f"Trigger recall: {tp}/{tp+fn} = {exact_rate(tp,tp+fn)}")
    print(f"Trigger confusion: TP={tp}, FP={fp}, FN={fn}, TN={tn}")
    print(f"Trigger observed: {trigger_observed}/{len(cases)} (missing is NOT RUN)")
    for field in ("tokens", "duration_ms"):
        for variant in VARIANTS:
            vals = telemetry[variant][field]
            if not vals:
                print(f"{field} {variant}: N/A (no real telemetry)")
                continue
            mean = Fraction(sum(vals), len(vals))
            population_variance = sum(((Fraction(v) - mean) ** 2 for v in vals), Fraction()) / len(vals)
            print(f"{field} {variant}: samples={len(vals)}, exact mean={mean}, exact population variance={population_variance} (across observed cases; not repeated-run variance)")
    if complete != len(cases):
        print("INCOMPLETE: remaining runs are NOT RUN or evidence invalid")
    return 0 if complete == len(cases) else 1


def parse_bool(value: str):
    return value == "true" if value in ("true", "false") else None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="action", required=True)
    setup = sub.add_parser("init"); setup.add_argument("skill_dir"); setup.add_argument("--workspace", required=True)
    p = sub.add_parser("plan"); p.add_argument("workspace")
    r = sub.add_parser("record")
    r.add_argument("workspace"); r.add_argument("--case", required=True); r.add_argument("--variant", choices=VARIANTS, required=True)
    r.add_argument("--passed", choices=("true", "false"), required=True)
    r.add_argument("--evidence", required=True)
    r.add_argument("--triggered", choices=("true", "false"))
    r.add_argument("--tokens", type=int); r.add_argument("--duration-ms", type=int)
    s = sub.add_parser("report"); s.add_argument("workspace")
    a = ap.parse_args()
    try:
        if a.action == "init": initialise(Path(a.skill_dir), Path(a.workspace))
        if a.action == "plan": plan(Path(a.workspace))
        if a.action == "record": record(Path(a.workspace), a.case, a.variant,
                                        parse_bool(a.passed), Path(a.evidence),
                                        parse_bool(a.triggered) if a.triggered else None,
                                        a.tokens, a.duration_ms)
        if a.action == "report": return report(Path(a.workspace))
    except (SkillError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
