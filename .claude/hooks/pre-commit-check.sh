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
# Fails open (exit 0) rather than blocking, on any parsing problem,
# and also when the command names a tree this hook cannot resolve:
# an unchecked commit is a smaller price than hooks run against the wrong checkout.

set -euo pipefail

payload="$(cat)"

command -v jq >/dev/null 2>&1 || exit 0

command="$(echo "$payload" | jq -r '.tool_input.command // empty' 2>/dev/null || true)"
[ -n "$command" ] || exit 0

# Self-filter: only act on `git commit`.
# Global options such as `-C <path>` or `-c foo=bar` may sit between `git` and the verb, so allow a run of option words (each optionally followed by its value) first.
# The verb has to be followed by whitespace or the end of the command, so that `git commit-graph` is left alone.
# And `git` has to start the command or follow a `;`, `&` or `|`, so that a command merely *mentioning* a commit does not pay for a full run.
# The cost of that anchoring is that an oddly wrapped commit (`time git commit ...`) goes unchecked, which is the safe direction for a hook that only checks.
commit_re='(^|[;&|])[[:space:]]*git[[:space:]]+(-[^[:space:]]*([[:space:]]+[^-[:space:];&|][^[:space:]]*)?[[:space:]]+)*commit([[:space:]]|$)'
# Quoted text is not a command: an issue or PR body can quote a whole command line, separators and all.
# Blank quoted spans out before deciding, but keep the original command for the path extraction below, where a quoted path is real.
# A heredoc body is not quoted this way, so one containing a commit line still costs a run: a slow hook rather than a wrong one.
unquoted="$(echo "$command" | sed -E "s/\"[^\"]*\"//g; s/'[^']*'//g")"
echo "$unquoted" | grep -qE "$commit_re" || exit 0

project_dir="${CLAUDE_PROJECT_DIR:-$(pwd)}"

# Which working tree does this commit target?
# In priority order: an explicit `-C <path>` or `--work-tree=<path>` on the git invocation,
# else a `cd` earlier in the same command,
# else the Bash tool's own working directory from the payload,
# else the project dir.
# `--git-dir` is deliberately not consulted: it names the git directory rather than the working tree,
# and for a linked worktree it points inside the primary checkout's `.git`, which is not a tree to run hooks in.
# A path may be quoted, and a quoted path may contain spaces,
# so the value of a flag is either a quoted run or an unquoted word.
value_after() {
  echo "$command" | sed -nE "s/.*$1(\"[^\"]*\"|'[^']*'|[^[:space:];&|]+).*/\1/p" | head -n1
}

# `named` records that the command pointed somewhere, resolvable or not.
named=""
target=""
if echo "$command" | grep -qE '[[:space:]]-C[[:space:]]'; then
  named="yes"
  target="$(value_after '[[:space:]]-C[[:space:]]+')"
elif echo "$command" | grep -qE '\-\-work-tree[=[:space:]]'; then
  named="yes"
  target="$(value_after '\-\-work-tree[=[:space:]]+')"
elif echo "$command" | grep -qE '(^|[;&|])[[:space:]]*cd[[:space:]]+'; then
  named="yes"
  target="$(echo "$command" | grep -oE '(^|[;&|])[[:space:]]*cd[[:space:]]+[^;&|]+' | tail -n1 | sed -E 's/^[;&|]?[[:space:]]*cd[[:space:]]+//')"
fi

# Strip surrounding quotes and whitespace, and expand a leading `~`.
target="$(echo "$target" | sed -E "s/^[[:space:]]*['\"]?//; s/['\"]?[[:space:]]*$//")"
case "$target" in
  "~"|"~/"*)
    # Guard HOME: `set -u` would abort on an unset one,
    # and aborting is the one thing this hook must not do.
    if [ -n "${HOME:-}" ]; then target="${HOME}${target#\~}"; else target=""; fi
    ;;
  *'$'*) target="" ;;  # set in an earlier Bash call, whose state this hook cannot see
esac

# Resolve to the root of whichever checkout the target names,
# so the hooks see the whole working tree.
# A linked worktree resolves to its own root, rather than to the primary checkout.
if [ -n "$named" ]; then
  # The command pointed somewhere. If that path cannot be resolved to a checkout,
  # because it was built from a variable set in an earlier Bash call,
  # or because it is not a checkout at all, then skip rather than guess:
  # running the hooks in some other tree would check the wrong files,
  # and any hook that rewrites one would rewrite it there.
  if [ -z "$target" ] || ! root="$(git -C "$target" rev-parse --show-toplevel 2>/dev/null)"; then
    exit 0
  fi
  target="$root"
else
  # Nothing was named, so the Bash tool's own working directory is the best guess,
  # and the project dir after that.
  cwd="$(echo "$payload" | jq -r '.cwd // empty' 2>/dev/null || true)"
  target="${cwd:-$project_dir}"
  if root="$(git -C "$target" rev-parse --show-toplevel 2>/dev/null)"; then
    target="$root"
  else
    target="$project_dir"
  fi
fi

if ! output=$(cd "$target" && uv run pre-commit run --all-files 2>&1); then
  echo "pre-commit failed in $target — fix the issues below before committing:" >&2
  echo "$output" >&2
  exit 2
fi
exit 0
