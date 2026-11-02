"""Check that a pull request has a milestone that is still open and agrees with its changelog entries.

The milestone of a pull request is the first release that ships it.
This check fails when the pull request has no milestone, when its milestone is closed (that release is out),
or when a changelog entry the pull request adds for itself sits under a release heading other than its milestone.
Entries under **Unreleased** agree with any open milestone.
Only entries that link this pull request count, as the changelog links each entry to the pull request that made it;
entries for other releases or other pull requests are left alone, for instance when a pull request tidies up the changelog.

It reads the pull request live from the GitHub API rather than from the event payload,
so that re-running it after a milestone was closed gives the current verdict.
It needs the ``gh`` CLI, authenticated with a token that can read the repository.

Usage::

    python .github/scripts/check_milestone.py <owner/repo> <pull request number> [changelog file ...]
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys

DEFAULT_CHANGELOGS = ("CHANGELOG.rst", "CHANGELOG-S2.rst")

# A section heading is a line underlined by a row of "=" characters.
UNDERLINE = re.compile(r"^=+\s*$")
# Release headings look like "v1.2.3 | 2026-11-02"; the leading "v" is optional.
RELEASE_HEADING = re.compile(r"^v?(\d+\.\d+\.\d+)\b")
# Hunk headers give the line number in the new file, e.g. "@@ -10,6 +10,8 @@".
HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
# Changelog entries are bullet points.
BULLET = re.compile(r"^\s*[*-] ")
# Changelog entries link the pull requests that made them, e.g. "`#236 <.../pull/236>`__".
PULL_REFERENCE = re.compile(r"(?:/pull/|#)(\d+)\b")


def gh_api(path: str) -> object:
    """Call the GitHub REST API through the ``gh`` CLI, following pagination for lists."""
    output = subprocess.run(
        ["gh", "api", "--paginate", "--slurp", path],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    pages = json.loads(output)
    if all(isinstance(page, list) for page in pages):
        return [item for page in pages for item in page]
    return pages[0]


def version_key(title: str) -> tuple:
    """Sort key for milestone titles, putting version-like titles in version order and the rest last."""
    match = RELEASE_HEADING.match(title)
    if match:
        return (0, tuple(int(part) for part in match.group(1).split(".")))
    return (1, title)


def added_lines(patch: str) -> list[tuple[int, str]]:
    """List the lines a diff adds, with their 1-indexed line numbers in the new file."""
    added = []
    new_line = 0
    for line in patch.splitlines():
        hunk = HUNK_HEADER.match(line)
        if hunk:
            new_line = int(hunk.group(1))
            continue
        if line.startswith("+"):
            added.append((new_line, line[1:]))
            new_line += 1
        elif line.startswith("-") or line.startswith("\\"):
            continue
        else:
            new_line += 1
    return added


def section_of(lines: list[str], line_number: int) -> str | None:
    """Return the heading of the section that a 1-indexed line falls under, or None above the first section."""
    for index in range(line_number - 1, 0, -1):
        if (
            UNDERLINE.match(lines[index])
            and lines[index - 1].strip()
            and not UNDERLINE.match(lines[index - 1])
        ):
            return lines[index - 1].strip()
    return None


def changelog_releases(
    changelog: str, patch: str, number: int
) -> dict[str, str | None]:
    """Map each changelog entry a diff adds for pull request ``number`` to the release its section names.

    The release is None for entries under Unreleased and under other sections.
    Entries that do not link this pull request are skipped.
    """
    lines = changelog.splitlines()
    releases = {}
    for line_number, text in added_lines(patch):
        if not BULLET.match(text):
            continue
        references = {int(reference) for reference in PULL_REFERENCE.findall(text)}
        if number not in references:
            continue
        heading = section_of(lines, line_number)
        match = RELEASE_HEADING.match(heading or "")
        releases[text.strip()] = match.group(1) if match else None
    return releases


def escape_command_data(text: str) -> str:
    """Escape text for the message of a GitHub Actions workflow command, so that changelog text cannot end it early."""
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def problems_with(
    milestone: dict | None,
    open_milestones: list[str],
    entries: dict[str, dict[str, str | None]],
) -> list[str]:
    """List what is wrong with a pull request's milestone, given the changelog entries it adds per file."""
    suggestion = (
        f" Open milestones: {', '.join(open_milestones)}."
        if open_milestones
        else " There is no open milestone; create one for the next release."
    )
    if milestone is None:
        return [
            "This pull request has no milestone. Set it to the first release that will ship this change."
            + suggestion
        ]
    title = milestone["title"]
    if milestone["state"] != "open":
        return [
            f"Milestone {title} is closed, so that release is already out. Move this pull request to the release that will ship it."
            + suggestion
        ]
    problems = []
    for path, releases in entries.items():
        for entry, release in releases.items():
            if release is not None and release != title.lstrip("v"):
                problems.append(
                    f"{path} lists this change under v{release}, but the milestone is {title}; make them agree. Entry: {entry[:120]}"
                )
    return problems


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    repo, number = argv[1], argv[2]
    changelogs = argv[3:] or list(DEFAULT_CHANGELOGS)

    pull = gh_api(f"repos/{repo}/pulls/{number}")
    head_sha = pull["head"]["sha"]
    milestones = gh_api(f"repos/{repo}/milestones?state=open&per_page=100")
    open_milestones = sorted((m["title"] for m in milestones), key=version_key)

    entries = {}
    for changed in gh_api(f"repos/{repo}/pulls/{number}/files?per_page=100"):
        if changed["filename"] in changelogs and changed.get("patch"):
            content = gh_api(
                f"repos/{repo}/contents/{changed['filename']}?ref={head_sha}"
            )
            text = base64.b64decode(content["content"]).decode("utf-8")
            entries[changed["filename"]] = changelog_releases(
                text, changed["patch"], int(number)
            )

    problems = problems_with(pull["milestone"], open_milestones, entries)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if problems:
        for problem in problems:
            print(f"::error title=Milestone::{escape_command_data(problem)}")
        report = (
            "### Milestone check failed\n\n"
            + "\n".join(f"- {problem}" for problem in problems)
            + "\n"
        )
    else:
        report = f"### Milestone check passed\n\nMilestone {pull['milestone']['title']} is open and agrees with the changelog.\n"
        print(report)
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(report)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
