"""Heuristic local security scan; no implication of a comprehensive security audit."""
import argparse
import re
import sys
from pathlib import Path
from _core import check_root, SkillError

PATTERNS = [
    ("embedded-private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("embedded-token", re.compile(r"(?:sk-[A-Za-z0-9_-]{24,}|ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})")),
    ("curl-pipe-shell", re.compile(r"\b(?:curl|wget)\b[^\n]{0,160}\|\s*(?:sh|bash)\b", re.I)),
    ("unsafe-git-clean", re.compile(r"\bgit\s+clean\s+-[^\n]*f", re.I)),
    ("unsafe-git-reset", re.compile(r"\bgit\s+reset\s+--hard\b", re.I)),
    ("unsafe-recursive-delete", re.compile(r"\brm\s+-[a-z]*r[a-z]*f\b|\brm\s+-[a-z]*f[a-z]*r\b", re.I)),
    ("shell-true", re.compile(r"shell\s*=\s*True")),
]
NEGATION = re.compile(r"(?:не\s+используй|не\s+выполняй|нельзя|никогда|без|never\s+(?:run|use)|do\s+not\s+(?:run|use)|запрещено|не\s+исполнять|нет\b)", re.I)


def audit(path: str):
    root = check_root(path)
    findings = []
    for file in root.rglob("*"):
        if file.is_symlink():
            findings.append((file.relative_to(root).as_posix(), 0, "symlink", "blocked"))
            continue
        if not file.is_file():
            continue
        relative = file.relative_to(root).as_posix()
        if file.name.startswith(".env") or file.suffix.lower() in {".key", ".pem", ".p12"}:
            findings.append((relative, 0, "sensitive-file", "blocked"))
        if file.suffix.lower() not in {".py", ".js", ".ts", ".sh", ".ps1", ".md", ".yaml", ".json", ".txt"}:
            continue
        try:
            text = file.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError):
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            for label, pattern in PATTERNS:
                if file.name == "audit_skill.py" and "re.compile(" in line:
                    continue
                # Fixture constructors are test data, not commands sent to the shell.
                if relative.startswith("tests/") and "write_text(" in line and label.startswith(("unsafe-", "curl-")):
                    continue
                if pattern.search(line):
                    # Explicitly prohibited command in docs is not an instruction to execute.
                    if (label.startswith(("unsafe-", "curl-")) or label == "shell-true") and NEGATION.search(line):
                        continue
                    findings.append((relative, number, label, "review"))
    return findings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("skill_dir")
    a = parser.parse_args()
    try:
        findings = audit(a.skill_dir)
    except SkillError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    for path, line, label, severity in findings:
        print(f"{severity.upper()}: {path}:{line} {label}")
    print(f"Security heuristics: {len(findings)} finding(s); manual review is still mandatory")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
