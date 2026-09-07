"""List the files a push would add, and flag the ones that look unintended.

A file can enter a branch without anyone deciding it should:
swept in by ``git add -A``, left behind by a merge, or carried along from another branch.
Modified files are almost always deliberate;
a brand-new file nobody mentioned is the thing worth a second look.

Advisory only.
It prints and exits 0, because it cannot know intent -- it can only ask whether the addition was meant.

Usage:
    python push_file_review.py            # compare against the tracked upstream, else origin/main
    python push_file_review.py <base>     # compare against an explicit base
"""

from __future__ import annotations

import re
import subprocess
import sys

#: Patterns whose additions are almost never deliberate.
SUSPICIOUS = [
    (re.compile(r"(^|/)\.[^/]+$"), "a dotfile"),
    (re.compile(r"\.(orig|rej|bak|tmp|swp)$"), "merge or editor debris"),
    (
        re.compile(r"(^|/|_|-)(local|scratch|probe|debug|tmp)[._/-]"),
        "a scratch-looking name",
    ),
    (re.compile(r"\.(log|pyc|pkl|sqlite3?|db)$"), "a build or runtime artifact"),
]

#: Directories a change is normally confined to.
#: Anything else is worth naming, rather than assuming it belongs.
EXPECTED_ROOTS = ("flexmeasures/", "documentation/", "tests/", ".github/", ".claude/")


def run(*args: str) -> str:
    return subprocess.run(args, capture_output=True, text=True).stdout.strip()


def pick_base(argv: list[str]) -> str | None:
    """The ref to compare against: an explicit argument, the tracked upstream, or origin/main."""
    if len(argv) > 1:
        return argv[1]
    upstream = run("git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    for candidate in (upstream, "origin/main"):
        if candidate and run("git", "rev-parse", "--verify", "--quiet", candidate):
            return candidate
    return None


def main() -> int:
    base = pick_base(sys.argv)
    if base is None:
        return 0
    merge_base = run("git", "merge-base", "HEAD", base)
    if not merge_base:
        return 0

    added = [
        name
        for name in run(
            "git", "diff", "--name-only", "--diff-filter=A", merge_base, "HEAD"
        ).split("\n")
        if name
    ]
    if not added:
        return 0

    flagged = []
    for name in added:
        for pattern, why in SUSPICIOUS:
            if pattern.search(name):
                flagged.append((name, why))
                break
        else:
            if not name.startswith(EXPECTED_ROOTS):
                flagged.append((name, "outside the usual directories"))

    print(f"This push adds {len(added)} file(s), compared against {base}:")
    for name in added:
        print(f"    {name}")
    if flagged:
        print("\nWorth confirming you meant to add these:")
        for name, why in flagged:
            print(f"    {name} — {why}")
        print("\nIf any of them is not part of this change, remove it before pushing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
