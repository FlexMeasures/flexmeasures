#!/usr/bin/env bash
# Advisory check, run before an agent commits: flag docstring and comment lines
# that break mid-phrase, looking only at the lines being added.
# Never blocks -- the check is a heuristic, and the agent judges each hit.
set -uo pipefail
cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0
command -v python3 >/dev/null 2>&1 || exit 0
python3 .claude/hooks/reflow_check.py --staged 2>/dev/null || true
exit 0
