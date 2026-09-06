"""Flag docstring and comment lines that break in the middle of a phrase.

The repo convention (see .github/instructions/docstrings.instructions.md) is that
each physical line of a docstring or comment ends at punctuation,
so that review comments and text search stay stable.
The mechanical form of that rule:
inside a multi-line docstring or comment block, every line but the last ends in punctuation.

This is a heuristic, and deliberately an advisory one --
docstrings here also hold OpenAPI YAML, shell commands and bullet lists,
none of which are prose and none of which end in punctuation.
The agent reading the output is expected to judge each hit rather than obey it.

Usage:
    python reflow_check.py <file>...          # whole files
    python reflow_check.py --staged           # only lines added in the git index
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

PUNCTUATION = (".", ",", ";", ":", "!", "?", ")", "]", "}", "-", "—", "–")

#: Lines that are not prose, and so are not expected to end in punctuation.
NOT_PROSE = re.compile(
    r"""^(
      \s*[-*+]\s          # bullet list item
    | \s*\.\.\s           # RST directive
    | \s*>>>              # doctest
    | \s*\$               # shell prompt
    | \s*\w[\w\s-]*:\s*\S # "key: value", i.e. embedded YAML
    | \s*[\[{]            # start of an embedded JSON/dict literal
    )""",
    re.VERBOSE,
)


def _offending_lines(block: list[str], first_line: int) -> list[tuple[int, str]]:
    """Lines of one block that end mid-phrase, ignoring the last line of the block."""
    found = []
    body = [(i, ln) for i, ln in enumerate(block) if ln.strip()]
    for i, line in body[:-1]:
        text = re.sub(r"^\s*#:?\s?", "", line).strip().strip('"').strip("'").strip()
        if not text or text.endswith("\\") or NOT_PROSE.match(line):
            continue
        if not text.endswith(PUNCTUATION):
            found.append((first_line + i, line.strip()[:110]))
    return found


def check(path: Path) -> list[tuple[int, str]]:
    """Every mid-phrase line break in one Python file."""
    try:
        source = path.read_text()
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError, OSError):
        return []

    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            docstring = ast.get_docstring(node, clean=False)
            if docstring and "\n" in docstring:
                first = node.body[0].lineno if node.body else 1
                found += _offending_lines(docstring.split("\n"), first)

    block: list[str] = []
    start = 0
    for number, line in enumerate(source.split("\n"), start=1):
        if line.strip().startswith("#"):
            start = start or number
            block.append(line)
            continue
        if len(block) > 1:
            found += _offending_lines(block, start)
        block, start = [], 0
    if len(block) > 1:
        found += _offending_lines(block, start)
    return found


def staged_lines() -> dict[str, set[int]]:
    """Line numbers added to each staged Python file."""
    diff = subprocess.run(
        ["git", "diff", "--cached", "-U0", "--", "*.py"],
        capture_output=True,
        text=True,
    ).stdout
    added: dict[str, set[int]] = {}
    current = None
    for line in diff.split("\n"):
        if line.startswith("+++ b/"):
            current = line[6:]
            added.setdefault(current, set())
        header = re.match(r"^@@ -\S+ \+(\d+)(?:,(\d+))?", line)
        if header and current:
            first = int(header.group(1))
            added[current].update(range(first, first + int(header.group(2) or 1)))
    return added


def main() -> int:
    if "--staged" in sys.argv:
        targets = staged_lines()
    else:
        targets = {argument: None for argument in sys.argv[1:]}

    hits = []
    for name, wanted in targets.items():
        path = Path(name)
        if not path.exists():
            continue
        for number, text in sorted(set(check(path))):
            if wanted is None or number in wanted:
                hits.append(f"{name}:{number}: {text}")

    if hits:
        print("Possible mid-phrase line breaks in docstrings or comments:")
        print("\n".join(f"  {hit}" for hit in hits))
        print(
            "\nEach line above should end at punctuation, or be reflowed so it does."
            "\nIgnore any that are not prose (embedded YAML, shell commands, list items)."
        )
    return 0  # advisory: never blocks the commit


if __name__ == "__main__":
    sys.exit(main())
