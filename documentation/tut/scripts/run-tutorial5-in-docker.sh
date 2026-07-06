#!/bin/bash

# Determine container name: use $1 if provided, otherwise construct from current folder name
CONTAINER_NAME="${1:-$(basename $(pwd))-server-1}"

echo "[TUTORIAL-RUNNER] RUNNING TUTORIAL 5 (REPORTERS / KPIs) ..."
echo "------------------------------------------------------------"

TOMORROW=$(date --date="next day" '+%Y-%m-%d')

eval "$(docker exec -i $CONTAINER_NAME flexmeasures add toy-account --kind battery --shell-vars)"
eval "$(docker exec -i $CONTAINER_NAME flexmeasures add toy-account --kind process --shell-vars)"
eval "$(docker exec -i $CONTAINER_NAME flexmeasures add toy-account --kind reporter --shell-vars)"

echo "[TUTORIAL-RUNNER] Setting up toy account with reporters..."

echo "[TUTORIAL-RUNNER] Show grid connection capacity ..."
docker exec -it $CONTAINER_NAME flexmeasures show beliefs --sensor ${FM_TOY_GRID_CAPACITY_SENSOR_ID} --start ${TOMORROW}T00:00:00+02:00 --duration PT24H --resolution PT1H

docker exec -it $CONTAINER_NAME flexmeasures show data-sources --show-attributes --id 6

echo "[TUTORIAL-RUNNER] Configure headroom reporter ..."

echo "
{
   'weights': {
       'grid connection capacity': 1.0,
       'PV': -1.0,
   }
}" > headroom-config.json
docker cp headroom-config.json $CONTAINER_NAME:/app

echo "
{
    'input': [{'name': 'grid connection capacity', 'sensor': ${FM_TOY_GRID_CAPACITY_SENSOR_ID}},
               {'name': 'PV', 'sensor': ${FM_TOY_SOLAR_SENSOR_ID}, 'sources': [4]}],
    'output': [{'sensor': ${FM_TOY_HEADROOM_SENSOR_ID}}]
}" > headroom-parameters.json
docker cp headroom-parameters.json $CONTAINER_NAME:/app


echo "[TUTORIAL-RUNNER] add headroom report ..."

docker exec -it $CONTAINER_NAME flexmeasures add report --reporter AggregatorReporter \
   --parameters headroom-parameters.json --config headroom-config.json \
   --start-offset DB,1D --end-offset DB,2D \
   --resolution PT15M


echo "[TUTORIAL-RUNNER] showing reported data ..."
docker exec -it $CONTAINER_NAME bash -c "flexmeasures show beliefs --sensor ${FM_TOY_HEADROOM_SENSOR_ID} --start ${TOMORROW}T00:00:00+01:00 --duration PT24H"


echo "[TUTORIAL-RUNNER] now the inflexible process ..."

echo "
{
    'input': [{'sensor': ${FM_TOY_PROCESS_INFLEXIBLE_SENSOR_ID}}],
    'output': [{'sensor': 9}]
}" > inflexible-parameters.json

docker cp inflexible-parameters.json $CONTAINER_NAME:/app

docker exec -it $CONTAINER_NAME flexmeasures add report --source 6 \
   --parameters inflexible-parameters.json \
   --start-offset DB,1D --end-offset DB,2D

echo "[TUTORIAL-RUNNER] showing reported data ..."
docker exec -it $CONTAINER_NAME bash -c "flexmeasures show beliefs --sensor 9 --start ${TOMORROW}T00:00:00+01:00 --duration PT24H"


echo "[TUTORIAL-RUNNER] now the breakable process ..."

echo "
{
    'input': [{'sensor': ${FM_TOY_PROCESS_BREAKABLE_SENSOR_ID}}],
    'output': [{'sensor': 10}]
}" > breakable-parameters.json

docker cp breakable-parameters.json $CONTAINER_NAME:/app

docker exec -it $CONTAINER_NAME flexmeasures add report --source 6 \
   --parameters breakable-parameters.json \
   --start-offset DB,1D --end-offset DB,2D

echo "[TUTORIAL-RUNNER] showing reported data ..."
docker exec -it $CONTAINER_NAME bash -c "flexmeasures show beliefs --sensor 10 --start ${TOMORROW}T00:00:00+01:00 --duration PT24H"



echo "[TUTORIAL-RUNNER] now the breakable process ..."

echo "
{
    'input' : [{'sensor': ${FM_TOY_PROCESS_SHIFTABLE_SENSOR_ID}}],
    'output' : [{'sensor': 11}]
}" > shiftable-parameters.json

docker cp shiftable-parameters.json $CONTAINER_NAME:/app

docker exec -it $CONTAINER_NAME flexmeasures add report --source 6 \
   --parameters shiftable-parameters.json \
   --start-offset DB,1D --end-offset DB,2D

echo "[TUTORIAL-RUNNER] showing reported data ..."
docker exec -it $CONTAINER_NAME bash -c "flexmeasures show beliefs --sensor 11 --start ${TOMORROW}T00:00:00+01:00 --duration PT24H"
