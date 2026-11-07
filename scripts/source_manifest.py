"""Inventory already downloaded local text sources offline; never execute or fetch them."""
import argparse
import json
import sys
from pathlib import Path
from _core import SkillError, check_root, hash_file, require_fresh_output

TEXT_SUFFIXES = {".md", ".mdx", ".txt", ".rst", ".py", ".js", ".ts", ".json", ".yaml", ".yml", ".toml", ".html", ".xml", ".go", ".rs"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "dist", "build"}
SKIP_NAMES = {".env", ".env.local", "credentials.json", "secrets.json"}


def generate(directory: Path, output: Path, max_file_bytes: int = 5_000_000) -> dict:
    root = check_root(str(directory))
    output = output.expanduser().absolute()
    require_fresh_output(output)
    if output.resolve().is_relative_to(root.resolve()):
        raise SkillError("Manifest output must be outside input directory")
    if max_file_bytes < 1:
        raise SkillError("max-file-bytes must be positive")
    records, skipped = [], []
    for item in sorted(root.rglob("*")):
        rel = item.relative_to(root)
        if any(p in SKIP_DIRS for p in rel.parts):
            continue
        if item.is_symlink():
            skipped.append({"path": rel.as_posix(), "reason": "symlink"})
            continue
        if not item.is_file():
            continue
        if item.name.lower() in SKIP_NAMES or item.suffix.lower() not in TEXT_SUFFIXES:
            skipped.append({"path": rel.as_posix(), "reason": "not-allowed-type-or-name"})
            continue
        size = item.stat().st_size
        if size > max_file_bytes:
            skipped.append({"path": rel.as_posix(), "reason": "over-size-limit"})
            continue
        records.append({"path": rel.as_posix(), "bytes": size, "sha256": hash_file(item)})
    result = {"schema_version": 1, "source_root": str(root), "files": records, "skipped": skipped,
              "scope": "inventory-only; no trust, correctness, or license assertions"}
    with output.open("x", encoding="utf-8") as sink:
        sink.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("source_dir")
    ap.add_argument("--output", required=True)
    ap.add_argument("--max-file-bytes", type=int, default=5_000_000)
    a = ap.parse_args()
    try:
        result = generate(Path(a.source_dir), Path(a.output), a.max_file_bytes)
    except (SkillError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(f"Inventoried {len(result['files'])} files; skipped {len(result['skipped'])}; no network access")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
