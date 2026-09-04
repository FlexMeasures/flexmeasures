#!/usr/bin/env python3
"""Work out which working tree the `git commit` in a Bash command targets.

Reads a Claude Code PreToolUse payload on stdin.
Prints the root of the tree to run the hooks in,
and prints nothing at all when the command is not a commit,
or when it names a tree that cannot be resolved from here.

The command is tokenised with `shlex`, so quoting and escaping are read the way a shell reads them.
Earlier versions of this hook matched the command with regular expressions,
and each round of review turned up another string that fooled them:
a quoted body holding `&& git commit`, an escaped quote inside such a body,
a path with a space in it, a second `-C` later in the line.
Tokenising removes that whole class of mistake,
because quoted text arrives as one token and cannot look like a command.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys

#: Tokens that end one command and start the next.
SEPARATORS = {"&&", "||", ";", "|", "&"}

#: Git's own options which take their value as the following token.
#: A `--flag=value` spelling carries its value with it, so it needs no entry here.
VALUE_OPTIONS = {
    "-C",
    "-c",
    "--git-dir",
    "--work-tree",
    "--namespace",
    "--super-prefix",
    "--config-env",
    "--exec-path",
}


def segments(tokens: list[str]) -> list[list[str]]:
    """Split a token list into the separate commands it holds."""
    found: list[list[str]] = [[]]
    for token in tokens:
        if token in SEPARATORS:
            found.append([])
        else:
            found[-1].append(token)
    return found


def _verb_and_options(tokens: list[str]) -> tuple[str | None, dict[str, str]]:
    """The git subcommand a segment invokes, and the values of git's own options before it.

    Returns `(None, {})` for anything that is not a git invocation.
    """
    if not tokens or os.path.basename(tokens[0]) != "git":
        return None, {}
    options: dict[str, str] = {}
    index = 1
    while index < len(tokens):
        token = tokens[index]
        if not token.startswith("-"):
            return token, options
        name, _, inline_value = token.partition("=")
        if inline_value:
            options[name] = inline_value
        elif name in VALUE_OPTIONS and index + 1 < len(tokens):
            index += 1
            options[name] = tokens[index]
        index += 1
    return None, options


def target_directory(command: str, cwd: str) -> str | None:
    """The directory whose hooks should run for this command, or None to run none.

    None means either that the command does not commit,
    or that it points at a tree this process cannot resolve:
    a path built from a shell variable set in an earlier call, or one that is not a checkout.
    Running the hooks somewhere else would check the wrong files,
    and any hook that rewrites one would rewrite it there, so nothing is the right answer.
    """
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None  # unbalanced quotes: not something to guess at

    named: str | None = None
    latest_cd: str | None = None
    committing = False
    for segment in segments(tokens):
        if segment and segment[0] == "cd" and len(segment) > 1:
            latest_cd = segment[1]
            continue
        verb, options = _verb_and_options(segment)
        if verb == "commit":
            committing = True
            # `--git-dir` is deliberately ignored: it names the git directory rather than the working tree,
            # and for a linked worktree it points inside the primary checkout.
            named = options.get("-C") or options.get("--work-tree")
            break
    if not committing:
        return None

    if named or latest_cd:
        return _toplevel(os.path.join(cwd, named or latest_cd or ""))
    # Nothing was named, so the Bash tool's own working directory is the best guess,
    # and the project directory after that.
    return _toplevel(cwd) or os.environ.get("CLAUDE_PROJECT_DIR") or None


def _toplevel(path: str) -> str | None:
    """The root of the checkout containing `path`, or None if it is not in one."""
    try:
        finished = subprocess.run(
            ["git", "-C", path, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if finished.returncode != 0:
        return None
    return finished.stdout.strip() or None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0  # never block a commit over a payload this hook cannot read
    command = (payload.get("tool_input") or {}).get("command") or ""
    cwd = payload.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    target = target_directory(command, cwd)
    if target:
        print(target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
