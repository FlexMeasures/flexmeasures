#!/usr/bin/env bash
# Advisory PreToolUse hook: warns (non-blocking) if no pytest/poe-test
# invocation is found in this session's transcript before a git commit.

input=$(cat)
transcript_path=$(echo "$input" | python3 -c "import json,sys; print(json.load(sys.stdin).get('transcript_path',''))" 2>/dev/null || true)

if [ -n "$transcript_path" ] && [ -f "$transcript_path" ]; then
  if ! grep -Eq '"command":"[^"]*(poe test|pytest)' "$transcript_path"; then
    echo "Reminder: no 'poe test' / 'pytest' run found yet in this session — consider running the test suite before committing." >&2
  fi
fi

exit 0
