#!/bin/bash

set -e
set -x

TOMORROW=$(date --date="next day" '+%Y-%m-%d')

# Write the 24 hourly rows as UTC times, starting at midnight in Amsterdam.
# Local times without an offset are ambiguous on the day the clocks go back
# (02:00 happens twice) and invalid on the day they go forward (02:00 does not exist).
START=$(TZ=Europe/Amsterdam date -u --date="TZ=\"Europe/Amsterdam\" ${TOMORROW} 00:00" '+%Y-%m-%dT%H:%M:%S')
PRICES=(10 11 12 15 18 17 10.5 9 9.5 9 8.5 10 8 5 4 4 5.5 8 12 13 14 12.5 10 7)

echo "Hour,Price" > prices-tomorrow.csv
for i in "${!PRICES[@]}"; do
  echo "$(date -u --date="${START} UTC + ${i} hours" '+%Y-%m-%dT%H:%M:%S'),${PRICES[$i]}" >> prices-tomorrow.csv
done
