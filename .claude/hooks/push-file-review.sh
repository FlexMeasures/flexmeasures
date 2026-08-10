#!/usr/bin/env bash
# Advisory check, run before an agent pushes: list the files this push adds,
# and flag any that look unintended.
# Never blocks -- it can only ask about intent.
set -uo pipefail
cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0
command -v python3 >/dev/null 2>&1 || exit 0
python3 .claude/hooks/push_file_review.py 2>/dev/null || true
exit 0
