#!/bin/bash

echo "[TUTORIAL-RUNNER] loading solar production data..."

TOMORROW=$(date --date="next day" '+%Y-%m-%d')
echo "Hour,Price
${TOMORROW}T00:00:00,0.0
${TOMORROW}T01:00:00,0.0
${TOMORROW}T02:00:00,0.0
${TOMORROW}T03:00:00,0.0
${TOMORROW}T04:00:00,0.01
${TOMORROW}T05:00:00,0.03
${TOMORROW}T06:00:00,0.06
${TOMORROW}T07:00:00,0.1
${TOMORROW}T08:00:00,0.14
${TOMORROW}T09:00:00,0.17
${TOMORROW}T10:00:00,0.19
${TOMORROW}T11:00:00,0.21
${TOMORROW}T12:00:00,0.22
${TOMORROW}T13:00:00,0.21
${TOMORROW}T14:00:00,0.19
${TOMORROW}T15:00:00,0.17
${TOMORROW}T16:00:00,0.14
${TOMORROW}T17:00:00,0.1
${TOMORROW}T18:00:00,0.06
${TOMORROW}T19:00:00,0.03
${TOMORROW}T20:00:00,0.01
${TOMORROW}T21:00:00,0.0
${TOMORROW}T22:00:00,0.0
${TOMORROW}T23:00:00,0.0" > solar-tomorrow.csv

docker cp solar-tomorrow.csv flexmeasures-server-1:/app

echo "[TUTORIAL-RUNNER] adding source ..."
docker exec -it flexmeasures-server-1 flexmeasures add source --name "toy-forecaster" --type forecaster
echo "[TUTORIAL-RUNNER] adding beliefs ..."
docker exec -it flexmeasures-server-1 flexmeasures add beliefs --sensor 3 --source 4 solar-tomorrow.csv --timezone Europe/Amsterdam

echo "[TUTORIAL-RUNNER] showing beliefs ..."
docker exec -it flexmeasures-server-1 bash -c "flexmeasures show beliefs --sensor 3 --start ${TOMORROW}T07:00:00+01:00 --duration PT12H"

echo "[TUTORIAL-RUNNER] update schedule taking solar into account ..."
docker exec -it flexmeasures-server-1 flexmeasures add schedule for-storage --sensor 2 --consumption-price-sensor 1 \
    --inflexible-device-sensor 3 \
    --start ${TOMORROW}T07:00+01:00 --duration PT12H \
    --soc-at-start 50% --roundtrip-efficiency 90%


echo "[TUTORIAL-RUNNER] showing schedule ..."
docker exec -it flexmeasures-server-1 bash -c "flexmeasures show beliefs --sensor 2 --start ${TOMORROW}T07:00:00+01:00 --duration PT12H"
