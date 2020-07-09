#!/bin/bash
set -e
# We are checking python files which have type hints, and leave out bigger issues we made issues for
# * data/scripts: We'll remove legacy code: https://trello.com/c/1wEnHOkK/7-remove-custom-data-scripts
# * data/models and data/services: https://trello.com/c/rGxZ9h2H/540-makequery-call-signature-is-incoherent
    files=$(find bvp \
    -not \( -path bvp/data/scripts -prune \) \
    -not \( -path bvp/data/models -prune \) \
    -not \( -path bvp/data/services -prune \) \
    -name \*.py | xargs grep -l "from typing import")
mypy --follow-imports skip --ignore-missing-imports $files 
