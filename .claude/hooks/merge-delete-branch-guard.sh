#!/usr/bin/env bash
# Blocking PreToolUse hook: disallow `gh pr merge` commands that include `--delete-branch`, because deleting in the same command can race ahead of GitHub's retargeting of stacked pull requests and close them.
#
# Exit 2 = blocking error.
# Exit 0 = allow.
# Fails open (exit 0) if parsing tools are unavailable.

set -euo pipefail

payload="$(cat)"

command -v jq >/dev/null 2>&1 || exit 0

command="$(echo "$payload" | jq -r '.tool_input.command // empty' 2>/dev/null || true)"
[ -n "$command" ] || exit 0

# Self-filter: not every Claude Code version honours the settings-level matcher.
echo "$command" | grep -qE '\bgh[[:space:]]+pr[[:space:]]+merge\b' || exit 0
echo "$command" | grep -q -- '--delete-branch' || exit 0

cat >&2 <<'EOF'
Blocked: do not merge and delete a branch in one `gh pr merge` command.
`--delete-branch` can race ahead of GitHub's retargeting of stacked pull requests and close them.

Use this order instead:
1. Merge without `--delete-branch`.
2. Check dependents: `gh pr list --base <branch> --state open`.
3. Delete the branch only when the check is empty, or let repository auto-delete handle it.
EOF
exit 2
