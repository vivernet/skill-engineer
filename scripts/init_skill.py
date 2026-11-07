"""Initialize a minimal Agent Skills skeleton without overwriting anything."""
import argparse
import json
import sys
from pathlib import Path
from _core import SkillError, require_name


def init(name: str, parent: Path, description: str, resources: list[str]) -> Path:
    require_name(name)
    if not description.strip() or len(description) > 1024 or "\n" in description:
        raise SkillError("Use one-line, non-empty description <=1024 chars")
    if any(r not in {"scripts", "references", "assets"} for r in resources):
        raise SkillError("Allowed resources: scripts,references,assets")
    parent = parent.expanduser().absolute()
    if not parent.is_dir():
        raise SkillError(f"Parent directory does not exist: {parent}")
    target = parent / name
    if target.exists() or target.is_symlink():
        raise SkillError(f"Target already exists, no changes made: {target}")
    # Guard before creating anything. This is a creation-only operation.
    target.mkdir(exist_ok=False)
    skill_text = f'''---\nname: {name}\ndescription: {json.dumps(description, ensure_ascii=False)}\n---\n\n# {name}\n\n## Назначение\n\nОпиши повторяемый результат и сценарии активации.\n\n## Процесс\n\n1. Проверь входные данные, права и ограничения.\n2. Выполни конкретную, безопасную последовательность.\n3. Проверь результат на наблюдаемых критериях.\n\n## Ошибки и безопасность\n\nНе удаляй незакоммиченные изменения. При недоступных инструментах не выдумывай результат.\n'''
    (target / "SKILL.md").write_text(skill_text, encoding="utf-8")
    (target / "agents").mkdir()
    ui_text = f'''interface:\n  display_name: "{name}"\n  short_description: "Reusable agent skill"\n  default_prompt: "Use ${name} to help with the relevant task."\n'''
    (target / "agents" / "openai.yaml").write_text(ui_text, encoding="utf-8")
    for resource in resources:
        (target / resource).mkdir()
    print(f"Created: {target}\nEdit SKILL.md and add prewritten eval scenarios BEFORE claiming readiness")
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name")
    parser.add_argument("--path", required=True, help="existing parent directory")
    parser.add_argument("--description", required=True)
    parser.add_argument("--resources", default="", help="comma-separated: scripts,references,assets")
    a = parser.parse_args()
    try:
        init(a.name, Path(a.path), a.description, [x for x in a.resources.split(",") if x])
    except (SkillError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
