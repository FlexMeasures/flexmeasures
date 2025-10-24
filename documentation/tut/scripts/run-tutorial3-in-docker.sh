#!/bin/bash

TOMORROW=$(date --date="next day" '+%Y-%m-%d')

echo "[TUTORIAL-RUNNER] Setting up toy account with reporters..."
docker exec -it flexmeasures-server-1 flexmeasures add toy-account --kind process

echo "[TUTORIAL-RUNNER] Creating three process schedules ..."
docker exec -it flexmeasures-server-1 flexmeasures add schedule --sensor 4 --scheduler ProcessScheduler \
  --start ${TOMORROW}T00:00:00+02:00 --duration PT24H \
  --flex-context '{"consumption-price": {"sensor": 1}}' \
  --flex-model '{"duration": "PT4H", "process-type": "INFLEXIBLE", "power": 0.2, "time-restrictions": [{"start": "'"${TOMORROW}"'T15:00:00+02:00", "duration": "PT1H"}]}'

docker exec -it flexmeasures-server-1 flexmeasures add schedule --sensor 5 --scheduler ProcessScheduler \
  --start ${TOMORROW}T00:00:00+02:00 --duration PT24H \
  --flex-context '{"consumption-price": {"sensor": 1}}' \
  --flex-model '{"duration": "PT4H", "process-type": "BREAKABLE", "power": 0.2, "time-restrictions": [{"start": "'"${TOMORROW}"'T15:00:00+02:00", "duration": "PT1H"}]}'

docker exec -it flexmeasures-server-1 flexmeasures add schedule --sensor 6 --scheduler ProcessScheduler \
  --start ${TOMORROW}T00:00:00+02:00 --duration PT24H \
  --flex-context '{"consumption-price": {"sensor": 1}}' \
  --flex-model '{"duration": "PT4H", "process-type": "SHIFTABLE", "power": 0.2, "time-restrictions": [{"start": "'"${TOMORROW}"'T15:00:00+02:00", "duration": "PT1H"}]}'

echo "Now visit http://localhost:5000/assets/5/graphs to see all three schedules."
