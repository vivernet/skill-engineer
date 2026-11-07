"""Safely package a validated skill in a fresh ZIP archive, without source changes."""
import argparse
import sys
import zipfile
from pathlib import Path
from _core import SkillError, check_root, require_fresh_output
from validate_skill import validate

SKIP_DIRS = {".git", "__pycache__", ".venv", "node_modules", ".pytest_cache"}
SKIP_EXT = {".pyc", ".pyo", ".log"}


def package(directory: Path, output: Path) -> int:
    root = check_root(str(directory))
    output = output.expanduser().absolute()
    require_fresh_output(output)
    if output.resolve().is_relative_to(root.resolve()):
        raise SkillError("Do not create ZIP inside the skill being packaged")
    result = validate(str(root), strict=True)
    if result["errors"]:
        raise SkillError("Validation failed: " + "; ".join(result["errors"]))
    archive_members = []
    for item in sorted(root.rglob("*")):
        relative = item.relative_to(root)
        if any(p in SKIP_DIRS for p in relative.parts):
            continue
        if item.is_symlink():
            raise SkillError(f"Symlink forbidden: {relative}")
        if not item.is_file() or item.suffix.lower() in SKIP_EXT:
            continue
        if item.stat().st_size > 10_000_000:
            raise SkillError(f"Large file requires review: {relative}")
        archive_members.append((item, f"{root.name}/{relative.as_posix()}"))
    if not archive_members:
        raise SkillError("No files to package")
    # Use exclusive file mode: never overwrite an existing archive, even with a race.
    with output.open("xb") as sink:
        with zipfile.ZipFile(sink, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for item, archive_name in archive_members:
                info = zipfile.ZipInfo(filename=archive_name, date_time=(2020, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                archive.writestr(info, item.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    print(f"Packaged {len(archive_members)} files: {output} (source untouched)")
    return len(archive_members)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("skill_dir")
    ap.add_argument("--output", required=True)
    a = ap.parse_args()
    try:
        package(Path(a.skill_dir), Path(a.output))
    except (SkillError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
