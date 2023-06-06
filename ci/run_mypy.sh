#!/bin/bash
set -e
pip install --upgrade 'mypy>=0.902'
pip install types-pytz types-requests types-Flask types-click types-redis types-tzlocal types-python-dateutil types-setuptools types-tabulate types-PyYAML
# We are checking python files which have type hints, and leave out bigger issues we made issues for
# * data/scripts: We'll remove legacy code: https://trello.com/c/1wEnHOkK/7-remove-custom-data-scripts
# * data/models and data/services: https://trello.com/c/rGxZ9h2H/540-makequery-call-signature-is-incoherent
    files=$(find flexmeasures \
    -not \( -path flexmeasures/data/scripts -prune \) \
    -not \( -path flexmeasures/data/models -prune \) \
    -not \( -path flexmeasures/data/services -prune \) \
    -name \*.py | xargs grep -l "from typing import")
mypy --follow-imports skip --ignore-missing-imports $files 
