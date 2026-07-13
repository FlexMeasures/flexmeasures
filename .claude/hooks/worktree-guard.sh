#!/usr/bin/env bash
# Blocking PreToolUse hook: the primary checkout is shared by multiple Claude
# Code agents. Branch-mutating git commands (checkout/switch/merge/rebase/
# reset/cherry-pick/stash) run there can switch the branch or rewrite history
# out from under another agent. This hook blocks those commands unless we're
# in a linked `git worktree` (or the command targets a directory outside the
# project via `cd`), where mutating the branch only affects that worktree.
#
# Exit 2 = blocking error (Claude sees stderr and can course-correct).
# Exit 0 = allow. Fails open (exit 0) on any parsing problem — never break
# the user's shell over a malformed hook payload or a missing `jq`.

set -euo pipefail

payload="$(cat)"

command -v jq >/dev/null 2>&1 || exit 0

command="$(echo "$payload" | jq -r '.tool_input.command // empty' 2>/dev/null || true)"
[ -n "$command" ] || exit 0

# Self-filter: only act on git commands that could mutate branch/worktree
# state. The settings-level "if" matcher is not honoured by all Claude Code
# versions, so replicate the filter here.
echo "$command" | grep -qE '(^|[;&|]|\bgit[[:space:]]+.*&&[[:space:]]*)git[[:space:]]+(checkout|switch|merge|rebase|reset|cherry-pick|stash)\b' || exit 0

# `git checkout -- <path>` / `git checkout <ref> -- <path>` only restore
# files from the index/a ref; they never move HEAD or the branch pointer.
# Allow those explicitly even though they match the "checkout" verb above.
if echo "$command" | grep -qE '\bgit[[:space:]]+checkout\b' && echo "$command" | grep -qE '\bgit[[:space:]]+checkout\b[^;&|]*--[[:space:]]'; then
  exit 0
fi

project_dir="${CLAUDE_PROJECT_DIR:-$(pwd)}"

# Allow if the command explicitly `cd`s outside the project dir first — same
# idea as the existing pre-commit-check.sh "target" logic: a `cd` elsewhere
# means the git command isn't acting on this shared checkout.
if echo "$command" | grep -qE '(^|[;&|])[[:space:]]*cd[[:space:]]+'; then
  target="$(echo "$command" | grep -oE '(^|[;&|])[[:space:]]*cd[[:space:]]+[^;&|]+' | tail -n1 | sed -E 's/^[;&|]?[[:space:]]*cd[[:space:]]+//')"
  target="$(eval echo "$target" 2>/dev/null || echo "$target")"
  case "$target" in
    "$project_dir"|"$project_dir"/*) : ;;
    /*)
      exit 0
      ;;
  esac
fi

# Only guard when running inside a git repo at all.
git_dir="$(git rev-parse --git-dir 2>/dev/null || true)"
[ -n "$git_dir" ] || exit 0

common_dir="$(git rev-parse --git-common-dir 2>/dev/null || true)"
[ -n "$common_dir" ] || exit 0

# Normalize to absolute paths for a reliable comparison.
git_dir_abs="$(cd "$(dirname "$git_dir")" 2>/dev/null && pwd)/$(basename "$git_dir")" || git_dir_abs="$git_dir"
common_dir_abs="$(cd "$(dirname "$common_dir")" 2>/dev/null && pwd)/$(basename "$common_dir")" || common_dir_abs="$common_dir"

# In a linked worktree, --git-dir (.../.git/worktrees/<name>) differs from
# --git-common-dir (.../.git). In the primary checkout they're the same.
# Mutating git state is safe in a linked worktree, so allow it there.
if [ "$git_dir_abs" != "$common_dir_abs" ]; then
  exit 0
fi

cat >&2 <<'EOF'
Blocked: this is the shared primary checkout — other agents may be working
here right now. Do not switch branches, merge, rebase, reset, cherry-pick,
or stash in it; doing so can yank the branch out from under another agent's
session and litter the tree with leftovers.

Create your own worktree and work there instead, e.g.:
  git worktree add --detach <scratchpad>/<name> <ref>
  # or, for a new branch:
  git worktree add -b <branch> <dir> <base>

Then cd into that worktree and retry. Read-only git commands (status, log,
diff, show, fetch, worktree, rev-parse, branch listing, etc.) and file-only
`git checkout -- <path>` restores are fine to run here.
EOF
exit 2
