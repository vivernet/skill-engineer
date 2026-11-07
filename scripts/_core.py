"""Small, intentionally dependency-free helpers for skill-engineer CLI scripts."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SAFE_REFERENCE = re.compile(r"(?<!!)\[[^\]\n]+\]\(([^)]+)\)")


class SkillError(ValueError):
    pass


def require_name(name: str) -> None:
    if not (1 <= len(name) <= 64) or not NAME_PATTERN.fullmatch(name):
        raise SkillError("Name must be 1..64 lowercase letters/digits with single hyphens, no edge hyphens")


def read_frontmatter(file: Path):
    """Read the common simple YAML subset; do not pretend this is a full YAML parser."""
    try:
        content = file.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise SkillError(f"Cannot read {file}: {exc}") from exc
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        raise SkillError("SKILL.md must begin with YAML frontmatter (---)")
    try:
        ending = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration as exc:
        raise SkillError("No closing --- for frontmatter") from exc
    front = lines[1:ending]
    values = {}
    for i, line in enumerate(front):
        if not line.strip() or line.lstrip().startswith("#") or line.startswith(" "):
            continue
        found = re.fullmatch(r"([a-zA-Z][\w-]*):\s*(.*)", line)
        if not found:
            raise SkillError(f"Unsupported top-level YAML at line {i+2}; use simple key: value or standard indented maps")
        key, val = found.groups()
        if key in values:
            raise SkillError(f"Duplicate frontmatter key: {key}")
        if val in ("|", ">", "|-", ">-"):
            block = []
            for continued in front[i + 1:]:
                if continued and not continued[0].isspace():
                    break
                if continued.startswith((" ", "\t")):
                    block.append(continued.strip())
            val = ("\n" if val.startswith("|") else " ").join(block)
        elif len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            try:
                val = val[1:-1].replace("''", "'") if val[0] == "'" else json.loads(val)
            except json.JSONDecodeError as exc:
                raise SkillError(f"Invalid double-quoted YAML value for {key}: {exc}") from exc
        values[key] = val
    body = "\n".join(lines[ending + 1:]).strip()
    return values, body, content


def check_root(path: str) -> Path:
    root = Path(path).expanduser().absolute()
    if root.is_symlink() or not root.is_dir():
        raise SkillError(f"Not a real skill directory: {root}")
    return root


def unsafe_relative_path(path: Path, root: Path) -> bool:
    return path.is_symlink() or not path.resolve().is_relative_to(root.resolve())


def hash_file(file: Path) -> str:
    dig = hashlib.sha256()
    with file.open("rb") as stream:
        for data in iter(lambda: stream.read(1 << 16), b""):
            dig.update(data)
    return dig.hexdigest()


def require_fresh_output(path: Path) -> None:
    if path.exists() or path.is_symlink():
        raise SkillError(f"Refusing to overwrite: {path}")
    if not path.parent.is_dir():
        raise SkillError(f"Output parent does not exist: {path.parent}")
