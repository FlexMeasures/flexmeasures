#!/usr/bin/env bash
# Lists merged PRs since the given (or latest) git tag that aren't yet
# mentioned in a changelog file, to help a human assemble
# documentation/changelog.rst / cli/change_log.rst / api/change_log.rst
# entries. Read-only: does not write to any changelog file or commit anything.
#
# Usage: ci/list-merged-prs-since-tag.sh [<since-tag>]
set -euo pipefail

SINCE="${1:-$(git describe --tags --abbrev=0)}"
SINCE_DATE=$(git log -1 --format=%aI "$SINCE")

REPO_ROOT=$(git rev-parse --show-toplevel)
CHANGELOG_FILES=(
  "$REPO_ROOT/documentation/changelog.rst"
  "$REPO_ROOT/documentation/cli/change_log.rst"
  "$REPO_ROOT/documentation/api/change_log.rst"
)
# PR numbers already referenced by a `PR #NNNN` link in any changelog file.
EXISTING_PRS=$(grep -ohP '(?<=PR #)\d+' "${CHANGELOG_FILES[@]}" 2>/dev/null | sort -un)

echo "Merged PRs since $SINCE ($SINCE_DATE) not yet mentioned in a changelog file:"
echo

gh pr list \
  --repo FlexMeasures/flexmeasures \
  --state merged \
  --search "merged:>=$SINCE_DATE" \
  --limit 200 \
  --json number,title,url \
  --jq '.[] | "\(.number)\t* \(.title) [see `PR #\(.number) <\(.url)>`_]"' \
  | while IFS=$'\t' read -r number line; do
      if grep -qx "$number" <<< "$EXISTING_PRS"; then
        continue
      fi
      echo "$line"
    done

echo
echo "Review, categorize into New features / Infrastructure / Support / Bugfixes,"
echo "and paste into documentation/changelog.rst (and cli/change_log.rst, api/change_log.rst if relevant)."
echo "(PRs already referenced in those files are omitted above.)"
