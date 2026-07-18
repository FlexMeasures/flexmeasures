#!/usr/bin/env bash
# Blocking PreToolUse hook: runs pre-commit before any `git commit` and blocks
# the commit if hooks fail or modify files. Exit 2 = blocking error (Claude
# sees stderr and can fix before retrying). Exit 0 = allow.

set -euo pipefail

if ! output=$(uv run pre-commit run --all-files 2>&1); then
    echo "pre-commit failed — fix the issues below before committing:" >&2
    echo "$output" >&2
    exit 2
  fi
  exit 0

