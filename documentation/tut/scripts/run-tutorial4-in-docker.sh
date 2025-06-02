#!/bin/bash

TOMORROW=$(date --date="next day" '+%Y-%m-%d')

echo "[TUTORIAL-RUNNER] Setting up toy account with reporters..."
docker exec -it flexmeasures-server-1  flexmeasures add toy-account --kind reporter


echo "[TUTORIAL-RUNNER] Show grid connection capacity (sensor 7)..."
docker exec -it flexmeasures-server-1 flexmeasures show beliefs --sensor 7 --start ${TOMORROW}T00:00:00+02:00 --duration PT24H --resolution PT1H

docker exec -it flexmeasures-server-1 flexmeasures show data-sources --show-attributes --id 6

echo "[TUTORIAL-RUNNER] Configure reporter ..."

echo "
{
   'weights' : {
       'grid connection capacity' : 1.0,
       'PV' : -1.0,
   }
}" > headroom-config.json
docker cp headroom-config.json flexmeasures-server-1:/app

echo "
{
    'input' : [{'name' : 'grid connection capacity','sensor' : 7},
               {'name' : 'PV', 'sensor' : 3}],
    'output' : [{'sensor' : 8}]
}" > headroom-parameters.json
docker cp headroom-parameters.json flexmeasures-server-1:/app


echo "[TUTORIAL-RUNNER] add report ..."

docker exec -it flexmeasures-server-1 flexmeasures add report --reporter AggregatorReporter \
   --parameters headroom-parameters.json --config headroom-config.json \
   --start-offset DB,1D --end-offset DB,2D \
   --resolution PT15M


echo "[TUTORIAL-RUNNER] showing reported data ..."
docker exec -it flexmeasures-server-1 bash -c "flexmeasures show beliefs --sensor 8 --start ${TOMORROW}T00:00:00+01:00 --duration PT24H"


echo "[TUTORIAL-RUNNER] now the inflexible process ..."

echo "
{
    'input' : [{'sensor' : 4}],
    'output' : [{'sensor' : 9}]
}" > inflexible-parameters.json

docker cp inflexible-parameters.json flexmeasures-server-1:/app

docker exec -it flexmeasures-server-1 flexmeasures add report --source 6 \
   --parameters inflexible-parameters.json \
   --start-offset DB,1D --end-offset DB,2D

echo "[TUTORIAL-RUNNER] showing reported data ..."
docker exec -it flexmeasures-server-1 bash -c "flexmeasures show beliefs --sensor 9 --start ${TOMORROW}T00:00:00+01:00 --duration PT24H"


echo "[TUTORIAL-RUNNER] now the breakable process ..."

echo "
{
    'input' : [{'sensor' : 5}],
    'output' : [{'sensor' : 10}]
}" > breakable-parameters.json

docker cp breakable-parameters.json flexmeasures-server-1:/app

docker exec -it flexmeasures-server-1 flexmeasures add report --source 6 \
   --parameters breakable-parameters.json \
   --start-offset DB,1D --end-offset DB,2D

echo "[TUTORIAL-RUNNER] showing reported data ..."
docker exec -it flexmeasures-server-1 bash -c "flexmeasures show beliefs --sensor 10 --start ${TOMORROW}T00:00:00+01:00 --duration PT24H"



echo "[TUTORIAL-RUNNER] now the breakable process ..."

echo "
{
    'input' : [{'sensor' : 6}],
    'output' : [{'sensor' : 11}]
}" > shiftable-parameters.json

docker cp shiftable-parameters.json flexmeasures-server-1:/app

docker exec -it flexmeasures-server-1 flexmeasures add report --source 6 \
   --parameters shiftable-parameters.json \
   --start-offset DB,1D --end-offset DB,2D

echo "[TUTORIAL-RUNNER] showing reported data ..."
docker exec -it flexmeasures-server-1 bash -c "flexmeasures show beliefs --sensor 11 --start ${TOMORROW}T00:00:00+01:00 --duration PT24H"

