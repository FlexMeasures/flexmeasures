#!/usr/bin/env bash
# Blocking PreToolUse hook: the primary checkout is shared by multiple Claude
# Code agents. Branch-mutating git commands (checkout/switch/merge/rebase/
# reset/cherry-pick/stash) run there can switch the branch or rewrite history
# out from under another agent, and `git stash` silently pockets other agents'
# uncommitted work. This hook blocks those commands when they target the
# primary checkout, and allows them when they target a linked `git worktree`,
# where mutating branch state only affects that worktree.
#
# Precision caveat: a PreToolUse hook does NOT run in the Bash tool's
# persistent working directory — it runs in the project dir. So this guard is
# "cwd + -C/--git-dir aware, not shell-state aware": if an agent ran
# `cd <worktree>` in an earlier Bash call and then runs a bare `git switch`,
# we evaluate against the primary checkout and block it. That is the safe
# direction to fail (annoying, not dangerous) — use `git -C <worktree> ...`,
# or `cd <worktree> && git ...` in the same command, to be recognised.
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
# versions, so replicate the filter here. Global options such as `-C <path>`,
# `--git-dir=<path>` or `-c foo=bar` may sit between `git` and the verb, so
# allow a run of option words (each optionally followed by its value) first.
verb_re='\bgit[[:space:]]+(-[^[:space:]]*([[:space:]]+[^-[:space:];&|][^[:space:]]*)?[[:space:]]+)*(checkout|switch|merge|rebase|reset|cherry-pick|stash)\b'
echo "$command" | grep -qE "$verb_re" || exit 0

# `git checkout -- <path>` / `git checkout <ref> -- <path>` only restore
# files from the index/a ref; they never move HEAD or the branch pointer.
# Allow those explicitly even though they match the "checkout" verb above.
if echo "$command" | grep -qE '\bcheckout\b[^;&|]*[[:space:]]--[[:space:]]'; then
  exit 0
fi

project_dir="${CLAUDE_PROJECT_DIR:-$(pwd)}"

# Work out which directory the git command actually targets, in priority
# order: an explicit `-C <path>` / `--git-dir=<path>` on the git invocation
# (the idiomatic way to drive another worktree without cd-ing), else a `cd`
# earlier in the same command (same idea as pre-commit-check.sh's target
# check), else the directory this hook runs in.
target=""
if echo "$command" | grep -qE '[[:space:]]-C[[:space:]]'; then
  target="$(echo "$command" | grep -oE '[[:space:]]-C[[:space:]]+[^[:space:];&|]+' | head -n1 | sed -E 's/^[[:space:]]*-C[[:space:]]+//')"
elif echo "$command" | grep -qE '\-\-git-dir[=[:space:]]'; then
  target="$(echo "$command" | grep -oE '\-\-git-dir[=[:space:]][^[:space:];&|]+' | head -n1 | sed -E 's/^--git-dir[=[:space:]]//')"
elif echo "$command" | grep -qE '(^|[;&|])[[:space:]]*cd[[:space:]]+'; then
  target="$(echo "$command" | grep -oE '(^|[;&|])[[:space:]]*cd[[:space:]]+[^;&|]+' | tail -n1 | sed -E 's/^[;&|]?[[:space:]]*cd[[:space:]]+//')"
fi

# Strip surrounding quotes/whitespace and expand ~ where we safely can. Do the
# expansion in a subshell with `set +u` so an unbound variable can't abort us.
target="$(echo "$target" | sed -E "s/^[[:space:]]*['\"]?//; s/['\"]?[[:space:]]*$//")"
if [ -n "$target" ]; then
  case "$target" in
    *['$~']*)
      # The path needs shell expansion. Only `~` is safe to expand here: a
      # variable like `-C "$WT"` was set in an earlier Bash call, whose state
      # this hook cannot see, so we cannot tell which checkout it points at.
      expanded="$(set +u; eval "echo $target" 2>/dev/null || true)"
      if [ -n "$expanded" ] && [ -d "$expanded" ]; then
        target="$expanded"
      else
        # Block rather than guess — the safe direction, same as a bare
        # `git switch` whose cwd we cannot see.
        unresolved="$target"
        target="$project_dir"
      fi
      ;;
  esac
fi

if [ -n "$target" ]; then
  # An absolute target outside the project dir entirely isn't our business.
  case "$target" in
    "$project_dir"|"$project_dir"/*) : ;;
    /*) exit 0 ;;
  esac
else
  target="$(pwd)"
fi

[ -d "$target" ] || exit 0

if [ -n "${unresolved:-}" ]; then
  cat >&2 <<EOF
Blocked: cannot verify where this git command points. Its target path
($unresolved) uses a shell variable this hook cannot see — a PreToolUse hook
does not share your shell's state, so it may well be the shared primary
checkout, where branch switching/merging clobbers other agents' sessions.

Re-run it with a literal path, which this hook can check:
  git -C /absolute/path/to/worktree <verb> ...
EOF
  exit 2
fi

# Only guard when the target is inside a git repo at all.
git_dir="$(git -C "$target" rev-parse --git-dir 2>/dev/null || true)"
common_dir="$(git -C "$target" rev-parse --git-common-dir 2>/dev/null || true)"
{ [ -n "$git_dir" ] && [ -n "$common_dir" ]; } || exit 0

# Normalize to absolute paths (git may return them relative to the target).
abspath() {
  local p="$1"
  case "$p" in
    /*) : ;;
    *) p="$target/$p" ;;
  esac
  (cd "$(dirname "$p")" 2>/dev/null && echo "$(pwd)/$(basename "$p")") || echo "$p"
}
git_dir_abs="$(abspath "$git_dir")"
common_dir_abs="$(abspath "$common_dir")"

# In a linked worktree, --git-dir (.../.git/worktrees/<name>) differs from
# --git-common-dir (.../.git). In the primary checkout they're the same.
# Mutating git state is safe in a linked worktree, so allow it there.
if [ "$git_dir_abs" != "$common_dir_abs" ]; then
  exit 0
fi

cat >&2 <<'EOF'
Blocked: this git command targets the shared primary checkout — other agents
may be working there right now. Do not switch branches, merge, rebase, reset
or cherry-pick in it: that yanks the branch out from under another agent's
session and litters the tree with leftovers. `git stash` is blocked for the
same reason — in a shared checkout it silently pockets *other agents'*
uncommitted work.

Create your own worktree and work there instead, e.g.:
  git worktree add --detach <scratchpad>/<name> <ref>
  # or, for a new branch:
  git worktree add -b <branch> <dir> <base>

Then target it explicitly — both of these forms are recognised:
  git -C <worktree> switch <branch>
  cd <worktree> && git merge main

Note: this hook cannot see your shell's persistent working directory, so a
bare `git switch` is always judged against the primary checkout even if you
cd'd into a worktree in an earlier call. Use `git -C <worktree> ...`.

Read-only git commands (status, log, diff, show, fetch, worktree, rev-parse,
branch listing, etc.) and file-only `git checkout -- <path>` restores are
fine to run here.
EOF
exit 2
