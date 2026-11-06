#!/bin/bash

set -euo pipefail

# Determine container name: use $1 if provided, otherwise construct from current folder name
CONTAINER_NAME="${1:-$(basename $(pwd))-server-1}"

echo "[TUTORIAL-RUNNER] RUNNING TUTORIAL 4 (PROCESS SCHEDULING) ..."
echo "------------------------------------------------------------"

TOMORROW=$(TZ=Europe/Amsterdam date --date="next day" '+%Y-%m-%d')
DAY_AFTER=$(TZ=Europe/Amsterdam date --date="${TOMORROW} + 1 day" '+%Y-%m-%d')
START=$(TZ=Europe/Amsterdam date --date="${TOMORROW} 00:00" '+%Y-%m-%dT%H:%M:%S%:z')
RESTRICTION_START=$(TZ=Europe/Amsterdam date --date="${TOMORROW} 15:00" '+%Y-%m-%dT%H:%M:%S%:z')
START_SECONDS=$(TZ=Europe/Amsterdam date --date="${TOMORROW} 00:00" '+%s')
END_SECONDS=$(TZ=Europe/Amsterdam date --date="${DAY_AFTER} 00:00" '+%s')
DURATION="PT$(( (END_SECONDS - START_SECONDS) / 3600 ))H"

echo "[TUTORIAL-RUNNER] Setting up toy account with processes..."
TOY_VARS=$(docker exec -i "$CONTAINER_NAME" flexmeasures add toy-account --kind process --shell-vars | grep '^FM_TOY_')
eval "$TOY_VARS"

echo "[TUTORIAL-RUNNER] Creating three process schedules ..."
docker exec -it $CONTAINER_NAME flexmeasures add schedule --sensor ${FM_TOY_PROCESS_INFLEXIBLE_SENSOR_ID} --scheduler ProcessScheduler \
  --start ${START} --duration ${DURATION} \
  --flex-context '{"consumption-price": {"sensor": '"${FM_TOY_PRICE_SENSOR_ID}"'}}' \
  --flex-model '{"duration": "PT4H", "process-type": "INFLEXIBLE", "power": 200, "time-restrictions": [{"start": "'"${RESTRICTION_START}"'", "duration": "PT1H"}]}'

docker exec -it $CONTAINER_NAME flexmeasures add schedule --sensor ${FM_TOY_PROCESS_BREAKABLE_SENSOR_ID} --scheduler ProcessScheduler \
  --start ${START} --duration ${DURATION} \
  --flex-context '{"consumption-price": {"sensor": '"${FM_TOY_PRICE_SENSOR_ID}"'}}' \
  --flex-model '{"duration": "PT4H", "process-type": "BREAKABLE", "power": 200, "time-restrictions": [{"start": "'"${RESTRICTION_START}"'", "duration": "PT1H"}]}'

docker exec -it $CONTAINER_NAME flexmeasures add schedule --sensor ${FM_TOY_PROCESS_SHIFTABLE_SENSOR_ID} --scheduler ProcessScheduler \
  --start ${START} --duration ${DURATION} \
  --flex-context '{"consumption-price": {"sensor": '"${FM_TOY_PRICE_SENSOR_ID}"'}}' \
  --flex-model '{"duration": "PT4H", "process-type": "SHIFTABLE", "power": 200, "time-restrictions": [{"start": "'"${RESTRICTION_START}"'", "duration": "PT1H"}]}'

echo "Now visit http://localhost:5000/assets/${FM_TOY_PROCESS_ASSET_ID}/graphs to see all three schedules."
