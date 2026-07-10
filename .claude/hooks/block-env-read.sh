#!/usr/bin/env bash
# Deny Bash commands that could read secret files, including recursive scans.
cmd=$(jq -r '.tool_input.command // ""')
if printf '%s' "$cmd" | grep -Eq '\.env([^a-zA-Z]|$)|secrets/|\.sql([^a-zA-Z]|$)'; then
  echo "Blocked: command references a secret file (.env/secrets/*.sql)." >&2
  exit 2
fi
# Recursive readers (grep -r / rg / find) that could walk into .env
if printf '%s' "$cmd" | grep -Eq '(grep[[:space:]]+-[a-zA-Z]*r|rg[[:space:]]|find[[:space:]])'; then
  echo "Blocked: recursive scan may read secret files. Narrow the path or exclude .env." >&2
  exit 2
fi
exit 0