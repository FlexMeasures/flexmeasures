#!/bin/bash

# Determine container name: use $1 if provided, otherwise construct from current folder name
CONTAINER_NAME="${1:-$(basename $(pwd))-server-1}"

echo "[TUTORIAL-RUNNER] RUNNING TUTORIAL 4 (PROCESS SCHEDULING) ..."
echo "------------------------------------------------------------"

TOMORROW=$(date --date="next day" '+%Y-%m-%d')

echo "[TUTORIAL-RUNNER] Setting up toy account with reporters..."
eval "$(docker exec -i $CONTAINER_NAME flexmeasures add toy-account --kind process --shell-vars | grep '^FM_TOY_')"

echo "[TUTORIAL-RUNNER] Creating three process schedules ..."
docker exec -it $CONTAINER_NAME flexmeasures add schedule --sensor ${FM_TOY_PROCESS_INFLEXIBLE_SENSOR_ID} --scheduler ProcessScheduler \
  --start ${TOMORROW}T00:00:00+02:00 --duration PT24H \
  --flex-context '{"consumption-price": {"sensor": '"${FM_TOY_PRICE_SENSOR_ID}"'}}' \
  --flex-model '{"duration": "PT4H", "process-type": "INFLEXIBLE", "power": 200, "time-restrictions": [{"start": "'"${TOMORROW}"'T15:00:00+02:00", "duration": "PT1H"}]}'

docker exec -it $CONTAINER_NAME flexmeasures add schedule --sensor ${FM_TOY_PROCESS_BREAKABLE_SENSOR_ID} --scheduler ProcessScheduler \
  --start ${TOMORROW}T00:00:00+02:00 --duration PT24H \
  --flex-context '{"consumption-price": {"sensor": '"${FM_TOY_PRICE_SENSOR_ID}"'}}' \
  --flex-model '{"duration": "PT4H", "process-type": "BREAKABLE", "power": 200, "time-restrictions": [{"start": "'"${TOMORROW}"'T15:00:00+02:00", "duration": "PT1H"}]}'

docker exec -it $CONTAINER_NAME flexmeasures add schedule --sensor ${FM_TOY_PROCESS_SHIFTABLE_SENSOR_ID} --scheduler ProcessScheduler \
  --start ${TOMORROW}T00:00:00+02:00 --duration PT24H \
  --flex-context '{"consumption-price": {"sensor": '"${FM_TOY_PRICE_SENSOR_ID}"'}}' \
  --flex-model '{"duration": "PT4H", "process-type": "SHIFTABLE", "power": 200, "time-restrictions": [{"start": "'"${TOMORROW}"'T15:00:00+02:00", "duration": "PT1H"}]}'

echo "Now visit http://localhost:5000/assets/6/graphs to see all three schedules."
