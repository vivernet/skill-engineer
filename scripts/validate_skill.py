"""Statically validate an Agent Skills directory; DOES NOT test agent behavior."""
import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit
from _core import SkillError, check_root, read_frontmatter, require_name, SAFE_REFERENCE

FORBIDDEN = {".env", ".env.local", "id_rsa", "id_ed25519", "credentials.json", "secrets.json"}


def validate(path: str, strict: bool = False) -> dict:
    errors, warnings = [], []
    try:
        root = check_root(path)
    except SkillError as exc:
        return {"errors": [str(exc)], "warnings": []}
    skill_file = root / "SKILL.md"
    if not skill_file.is_file() or skill_file.is_symlink():
        return {"errors": ["Missing regular SKILL.md"], "warnings": []}
    try:
        fields, body, source = read_frontmatter(skill_file)
    except SkillError as exc:
        return {"errors": [str(exc)], "warnings": []}
    allowed_fields = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
    for key in fields:
        if key not in allowed_fields:
            warnings.append(f"Non-standard metadata field: {key}")
    try:
        require_name(fields.get("name", ""))
        if root.name != fields["name"]:
            errors.append("Skill directory name must equal frontmatter name")
    except SkillError as exc:
        errors.append(str(exc))
    desc = fields.get("description", "").strip()
    if not desc or len(desc) > 1024:
        errors.append("description must be 1..1024 characters")
    if not body:
        errors.append("Body after frontmatter must not be empty")
    if fields.get("compatibility") is not None and len(fields["compatibility"]) > 500:
        errors.append("compatibility must be <=500 characters")
    if any(x in body for x in ("Опиши повторяемый", "Замените это предложение", "TODO: ")):
        warnings.append("Unresolved placeholder/TODO in SKILL.md")
    if len(body) > 40000:
        warnings.append("SKILL.md is large: consider references/ for progressive disclosure")
    for file in root.rglob("*"):
        relative = file.relative_to(root)
        if file.is_symlink():
            errors.append(f"Symlink forbidden: {relative.as_posix()}")
            continue
        if not file.is_file():
            continue
        if file.name.lower() in FORBIDDEN or file.name.lower().startswith(".env") or file.suffix.lower() in {".pem", ".p12", ".key"}:
            errors.append(f"Sensitive filename: {relative.as_posix()}")
    for md in root.rglob("*.md"):
        if md.is_symlink():
            continue
        for link in SAFE_REFERENCE.findall(md.read_text(encoding="utf-8-sig")):
            link = link.strip().split(" ", 1)[0].strip("<>")
            if link.startswith("#") or re.match(r"^(https?://|mailto:)", link):
                continue
            parsed = urlsplit(link)
            if parsed.scheme:
                continue
            # absolute paths and traversal are not acceptable references inside a skill.
            if Path(unquote(parsed.path)).is_absolute() or re.match(r"^[A-Za-z]:", parsed.path):
                errors.append(f"Absolute reference: {md.relative_to(root)} -> {link}")
                continue
            candidate = (md.parent / unquote(parsed.path)).resolve()
            if not candidate.is_relative_to(root.resolve()):
                errors.append(f"Escaping reference: {md.relative_to(root)} -> {link}")
            elif parsed.path and not candidate.exists():
                errors.append(f"Broken local reference: {md.relative_to(root)} -> {link}")
    if strict and warnings:
        errors.extend(f"STRICT: {w}" for w in warnings)
    return {"errors": sorted(set(errors)), "warnings": sorted(set(warnings))}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("skill_dir")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    result = validate(a.skill_dir, a.strict)
    if a.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for key in ("errors", "warnings"):
            for item in result[key]:
                print(f"{key.upper()}: {item}")
        print(f"Static validation: {'FAIL' if result['errors'] else 'PASS'} (not a behavioral test)")
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
