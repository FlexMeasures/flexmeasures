#!/usr/bin/env bash
# Blocking PreToolUse hook: runs pre-commit before any `git commit`,
# and blocks the commit if hooks fail or modify files.
# Exit 2 = blocking error (Claude sees stderr and can fix before retrying).
# Exit 0 = allow.
#
# A PreToolUse hook runs in the project dir and does not share the Bash tool's shell state,
# so there are two things this hook has to work out for itself.
#
# 1. Whether the command is a commit at all.
#    The settings-level "if" matcher is not honoured by all Claude Code versions, so the filter is repeated here, as worktree-guard.sh does.
#    Without it, an unrelated command such as `gh issue create` pays for a full `pre-commit run --all-files`.
# 2. Which working tree the commit targets. The primary checkout is shared by several agents.
#    Running the hooks there when the commit is really for a worktree checks the wrong tree,
#    and any hook that rewrites a file (such as the OpenAPI spec) dirties another agent's work.
#    The command text is the most reliable signal, since `cd <worktree> && git commit` leaves no trace in the payload's `cwd` once the shell's directory has been reset.
#
# Both answers come from pre_commit_target.py, which tokenises the command rather than matching it,
# and prints the directory to run in, or nothing when there is nothing safe to run.
# See that file for why the parsing lives in Python.
#
# Fails open (exit 0) rather than blocking, whenever the answer is not clear:
# an unchecked commit is a smaller price than hooks run against the wrong checkout.

set -euo pipefail

payload="$(cat)"

command -v python3 >/dev/null 2>&1 || exit 0

target="$(printf '%s' "$payload" | python3 "$(dirname "${BASH_SOURCE[0]}")/pre_commit_target.py" 2>/dev/null || true)"
[ -n "$target" ] || exit 0

if ! output=$(cd "$target" && uv run pre-commit run --all-files 2>&1); then
    echo "pre-commit failed in $target — fix the issues below before committing:" >&2
    echo "$output" >&2
    exit 2
fi
exit 0
