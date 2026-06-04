#!/bin/bash

# Determine container name: use $1 if provided, otherwise construct from current folder name
CONTAINER_NAME="${1:-$(basename $(pwd))-server-1}"

echo "[TUTORIAL-RUNNER] RUNNING TUTORIAL 1 (SIMPLE BATTERY SCHEDULE)..."
echo "-----------------------------------------------------------------"

echo "[TUTORIAL-RUNNER] loading prices..."
TOMORROW=$(date --date="next day" '+%Y-%m-%d')
echo "Hour,Price
${TOMORROW}T00:00:00,0.010
${TOMORROW}T01:00:00,0.011
${TOMORROW}T02:00:00,0.012
${TOMORROW}T03:00:00,0.015
${TOMORROW}T04:00:00,0.018
${TOMORROW}T05:00:00,0.017
${TOMORROW}T06:00:00,0.0105
${TOMORROW}T07:00:00,0.009
${TOMORROW}T08:00:00,0.0095
${TOMORROW}T09:00:00,0.009
${TOMORROW}T10:00:00,0.0085
${TOMORROW}T11:00:00,0.010
${TOMORROW}T12:00:00,0.008
${TOMORROW}T13:00:00,0.005
${TOMORROW}T14:00:00,0.004
${TOMORROW}T15:00:00,0.004
${TOMORROW}T16:00:00,0.0055
${TOMORROW}T17:00:00,0.008
${TOMORROW}T18:00:00,0.012
${TOMORROW}T19:00:00,0.013
${TOMORROW}T20:00:00,0.014
${TOMORROW}T21:00:00,0.0125
${TOMORROW}T22:00:00,0.010
${TOMORROW}T23:00:00,0.007" > prices-tomorrow.csv

docker cp prices-tomorrow.csv $CONTAINER_NAME:/app

docker exec -it $CONTAINER_NAME flexmeasures add beliefs \
  --sensor 1 --source toy-user /app/prices-tomorrow.csv --timezone Europe/Amsterdam

echo "[TUTORIAL-RUNNER] creating schedule ..."
docker exec -it $CONTAINER_NAME flexmeasures add schedule \
  --sensor 2 \
  --start ${TOMORROW}T07:00+01:00 --duration PT12H --soc-at-start 50% \
  --flex-model '{"soc-min": "50 kWh"}'

echo "[TUTORIAL-RUNNER] displaying schedule..."
docker exec -it $CONTAINER_NAME flexmeasures show beliefs \
  --sensor 2 --start ${TOMORROW}T07:00:00+01:00 --duration PT12H
