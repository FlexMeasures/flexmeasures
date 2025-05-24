#!/bin/bash

TOMORROW=$(date --date="next day" '+%Y-%m-%d')

echo "[TUTORIAL-RUNNER] Setting up toy account with reporters..."
docker exec -it flexmeasures-server-1  flexmeasures add toy-account --kind process


echo "[TUTORIAL-RUNNER] Creating three process schedules ..."
docker exec -it flexmeasures-server-1 flexmeasures add schedule for-process --sensor 4 --consumption-price-sensor 1\
  --start ${TOMORROW}T00:00:00+02:00 --duration PT24H --process-duration PT4H \
  --process-power 0.2MW --process-type INFLEXIBLE \
  --forbid "{\"start\" : \"${TOMORROW}T15:00:00+02:00\", \"duration\" : \"PT1H\"}"

docker exec -it flexmeasures-server-1 flexmeasures add schedule for-process --sensor 5 --consumption-price-sensor 1\
  --start ${TOMORROW}T00:00:00+02:00 --duration PT24H --process-duration PT4H \
  --process-power 0.2MW --process-type BREAKABLE \
  --forbid "{\"start\" : \"${TOMORROW}T15:00:00+02:00\", \"duration\" : \"PT1H\"}"

docker exec -it flexmeasures-server-1 flexmeasures add schedule for-process --sensor 6 --consumption-price-sensor 1\
  --start ${TOMORROW}T00:00:00+02:00 --duration PT24H --process-duration PT4H \
  --process-power 0.2MW --process-type SHIFTABLE \
  --forbid "{\"start\" : \"${TOMORROW}T15:00:00+02:00\", \"duration\" : \"PT1H\"}"
