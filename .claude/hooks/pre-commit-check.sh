#!/usr/bin/env bash
# Blocking PreToolUse hook: runs pre-commit before any `git commit` and blocks
# the commit if hooks fail or modify files. Exit 2 = blocking error (Claude
# sees stderr and can fix before retrying). Exit 0 = allow.
#
# Two things this hook has to work out for itself, because a PreToolUse hook
# runs in the project dir and does not share the Bash tool's shell state.
#
# 1. Whether the command is a commit at all. The settings-level "if" matcher
#    is not honoured by all Claude Code versions, so the filter is repeated
#    here, as worktree-guard.sh does. Without it, an unrelated command such as
#    `gh issue create` pays for a full `pre-commit run --all-files`.
# 2. Which working tree the commit targets. The primary checkout is shared by several agents.
#    Running the hooks there when the commit is really for a worktree checks the wrong tree,
#    and any hook that rewrites a file (such as the OpenAPI spec) dirties another agent's work.
#    The command text is the most reliable signal, since `cd <worktree> && git commit` leaves no trace in the payload's `cwd` once the shell's directory has been reset.
#
# Fails open (exit 0) on any parsing problem — never block a commit because the
# hook could not read its own payload.

set -euo pipefail

payload="$(cat)"

command -v jq >/dev/null 2>&1 || exit 0

command="$(echo "$payload" | jq -r '.tool_input.command // empty' 2>/dev/null || true)"
[ -n "$command" ] || exit 0

# Self-filter: only act on `git commit`. Global options such as `-C <path>` or
# `-c foo=bar` may sit between `git` and the verb, so allow a run of option
# words (each optionally followed by its value) first. The verb has to be
# followed by whitespace or the end of the command, so that `git commit-graph`
# is left alone, and `git` has to start the command or follow a `;`, `&` or `|`,
# so that a command merely *mentioning* a commit — an issue or PR body quoting
# `git commit -s`, say — does not pay for a full run. The cost of that anchoring
# is that an oddly wrapped commit (`time git commit ...`) goes unchecked, which
# is the safe direction for a hook that only checks.
commit_re='(^|[;&|])[[:space:]]*git[[:space:]]+(-[^[:space:]]*([[:space:]]+[^-[:space:];&|][^[:space:]]*)?[[:space:]]+)*commit([[:space:]]|$)'
# Quoted text is not a command: an issue or PR body can quote a whole command
# line, separators and all. Blank quoted spans out before deciding, but keep the
# original command for the path extraction below, where a quoted path is real.
# A heredoc body is not quoted this way, so one containing a commit line still
# costs a run; the failure mode is a slow hook, not a wrong one.
unquoted="$(echo "$command" | sed -E "s/\"[^\"]*\"//g; s/'[^']*'//g")"
echo "$unquoted" | grep -qE "$commit_re" || exit 0

project_dir="${CLAUDE_PROJECT_DIR:-$(pwd)}"

# Which working tree does this commit target? In priority order: an explicit
# `-C <path>` / `--work-tree=<path>` on the git invocation, else a `cd` earlier
# in the same command, else the Bash tool's own working directory from the
# payload, else the project dir. `--git-dir` is deliberately not consulted: it
# names the git directory rather than the working tree, and for a linked
# worktree it points inside the primary checkout's `.git`, which is not a tree
# to run hooks in.
# A path may be quoted, and a quoted path may contain spaces, so the value of a
# flag is either a quoted run or an unquoted word.
value_after() {
  echo "$command" | sed -nE "s/.*$1(\"[^\"]*\"|'[^']*'|[^[:space:];&|]+).*/\1/p" | head -n1
}

target=""
if echo "$command" | grep -qE '[[:space:]]-C[[:space:]]'; then
  target="$(value_after '[[:space:]]-C[[:space:]]+')"
elif echo "$command" | grep -qE '\-\-work-tree[=[:space:]]'; then
  target="$(value_after '\-\-work-tree[=[:space:]]+')"
elif echo "$command" | grep -qE '(^|[;&|])[[:space:]]*cd[[:space:]]+'; then
  target="$(echo "$command" | grep -oE '(^|[;&|])[[:space:]]*cd[[:space:]]+[^;&|]+' | tail -n1 | sed -E 's/^[;&|]?[[:space:]]*cd[[:space:]]+//')"
fi

# Strip surrounding quotes and whitespace, and expand a leading `~`.
target="$(echo "$target" | sed -E "s/^[[:space:]]*['\"]?//; s/['\"]?[[:space:]]*$//")"
case "$target" in
  "~"|"~/"*)
    # Guard HOME: `set -u` would abort on an unset one, and aborting is the one
    # thing this hook must not do.
    if [ -n "${HOME:-}" ]; then target="${HOME}${target#\~}"; else target=""; fi
    ;;
  *'$'*) target="" ;;  # set in an earlier Bash call, whose state this hook cannot see
esac

# Fall back to the working directory the Bash tool reports, then to the project.
if [ -z "$target" ]; then
  target="$(echo "$payload" | jq -r '.cwd // empty' 2>/dev/null || true)"
fi
[ -n "$target" ] || target="$project_dir"

# Resolve to the root of whichever checkout that is, so the hooks see the whole
# working tree. A linked worktree resolves to its own root, not the primary one.
if root="$(git -C "$target" rev-parse --show-toplevel 2>/dev/null)"; then
  target="$root"
else
  target="$project_dir"
fi

if ! output=$(cd "$target" && uv run pre-commit run --all-files 2>&1); then
  echo "pre-commit failed in $target — fix the issues below before committing:" >&2
  echo "$output" >&2
  exit 2
fi
exit 0
