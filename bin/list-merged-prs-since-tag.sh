#!/usr/bin/env bash
# Lists merged PRs since the given (or latest) git tag, to help a human
# assemble documentation/changelog.rst / cli/change_log.rst / api/change_log.rst
# entries. Read-only: does not write to any changelog file or commit anything.
#
# Usage: bin/list-merged-prs-since-tag.sh [<since-tag>]
set -euo pipefail

SINCE="${1:-$(git describe --tags --abbrev=0)}"
SINCE_DATE=$(git log -1 --format=%aI "$SINCE")

echo "Merged PRs since $SINCE ($SINCE_DATE):"
echo

gh pr list \
  --repo FlexMeasures/flexmeasures \
  --state merged \
  --search "merged:>=$SINCE_DATE" \
  --limit 200 \
  --json number,title,url \
  --template '{{range .}}* {{.title}} [see `PR #{{.number}} <{{.url}}>`_]{{"\n"}}{{end}}'

echo
echo "Review, categorize into New features / Infrastructure / Support / Bugfixes,"
echo "and paste into documentation/changelog.rst (and cli/change_log.rst, api/change_log.rst if relevant)."
