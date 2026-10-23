#!/bin/bash

set -euo pipefail

# Determine container name: use $1 if provided, otherwise construct from current folder name
CONTAINER_NAME="${1:-$(basename $(pwd))-server-1}"

extract_single_id() {
    local table_output="$1"
    local row_label="$2"
    local entity_description="$3"
    local ids

    ids=$(awk -v row_label="$row_label" \
        '$1 ~ /^[0-9]+$/ && index($0, row_label) {print $1}' \
        <<< "$table_output")

    if [[ $(wc -w <<< "$ids") -ne 1 ]]; then
        echo "[TUTORIAL-RUNNER] Expected exactly one ${entity_description}, but found: ${ids:-none}" >&2
        return 1
    fi

    printf '%s\n' "$ids"
}

echo "[TUTORIAL-RUNNER] RUNNING TUTORIAL 5 (REPORTERS / KPIs) ..."
echo "------------------------------------------------------------"

TOMORROW=$(date --date="next day" '+%Y-%m-%d')

eval "$(docker exec -i "$CONTAINER_NAME" flexmeasures add toy-account --kind battery --shell-vars | grep '^FM_TOY_')"
eval "$(docker exec -i "$CONTAINER_NAME" flexmeasures add toy-account --kind process --shell-vars | grep '^FM_TOY_')"
eval "$(docker exec -i "$CONTAINER_NAME" flexmeasures add toy-account --kind reporter --shell-vars | grep '^FM_TOY_')"

DATA_SOURCES=$(docker exec -i "$CONTAINER_NAME" flexmeasures show data-sources)
FM_TOY_PROFIT_OR_LOSS_REPORTER_SOURCE_ID=$(extract_single_id \
    "$DATA_SOURCES" "ProfitOrLossReporter" "ProfitOrLossReporter data source")

PROCESS_ASSET=$(docker exec -i "$CONTAINER_NAME" flexmeasures show asset --id "$FM_TOY_PROCESS_ASSET_ID")
FM_TOY_PROCESS_INFLEXIBLE_COST_SENSOR_ID=$(extract_single_id \
    "$PROCESS_ASSET" "costs (Inflexible)" "inflexible-process cost sensor")
FM_TOY_PROCESS_BREAKABLE_COST_SENSOR_ID=$(extract_single_id \
    "$PROCESS_ASSET" "costs (Breakable)" "breakable-process cost sensor")
FM_TOY_PROCESS_SHIFTABLE_COST_SENSOR_ID=$(extract_single_id \
    "$PROCESS_ASSET" "costs (Shiftable)" "shiftable-process cost sensor")

echo "[TUTORIAL-RUNNER] Setting up toy account with reporters..."

echo "[TUTORIAL-RUNNER] Show grid connection capacity ..."
docker exec -it "$CONTAINER_NAME" flexmeasures show beliefs --sensor "$FM_TOY_GRID_CAPACITY_SENSOR_ID" --start "${TOMORROW}T00:00:00+02:00" --duration PT24H --resolution PT1H

docker exec -it "$CONTAINER_NAME" flexmeasures show data-sources --show-attributes --id "$FM_TOY_PROFIT_OR_LOSS_REPORTER_SOURCE_ID"

echo "[TUTORIAL-RUNNER] Configure headroom reporter ..."

echo "
{
   'weights': {
       'grid connection capacity': 1.0,
       'PV': -1.0,
   }
}" > headroom-config.json
docker cp headroom-config.json "$CONTAINER_NAME":/app

echo "
{
    'input': [{'name': 'grid connection capacity', 'sensor': ${FM_TOY_GRID_CAPACITY_SENSOR_ID}},
               {'name': 'PV', 'sensor': ${FM_TOY_SOLAR_SENSOR_ID}, 'sources': [2]}],
    'output': [{'sensor': ${FM_TOY_HEADROOM_SENSOR_ID}}]
}" > headroom-parameters.json
docker cp headroom-parameters.json "$CONTAINER_NAME":/app


echo "[TUTORIAL-RUNNER] add headroom report ..."

docker exec -it "$CONTAINER_NAME" flexmeasures add report --reporter AggregatorReporter \
   --parameters headroom-parameters.json --config headroom-config.json \
   --start-offset DB,1D --end-offset DB,2D \
   --resolution PT15M


echo "[TUTORIAL-RUNNER] showing reported data ..."
docker exec -it "$CONTAINER_NAME" bash -c "flexmeasures show beliefs --sensor ${FM_TOY_HEADROOM_SENSOR_ID} --start ${TOMORROW}T00:00:00+01:00 --duration PT24H"


echo "[TUTORIAL-RUNNER] now the inflexible process ..."

echo "
{
    'input': [{'sensor': ${FM_TOY_PROCESS_INFLEXIBLE_SENSOR_ID}}],
    'output': [{'sensor': ${FM_TOY_PROCESS_INFLEXIBLE_COST_SENSOR_ID}}]
}" > inflexible-parameters.json

docker cp inflexible-parameters.json "$CONTAINER_NAME":/app

docker exec -it "$CONTAINER_NAME" flexmeasures add report --source "$FM_TOY_PROFIT_OR_LOSS_REPORTER_SOURCE_ID" \
   --parameters inflexible-parameters.json \
   --start-offset DB,1D --end-offset DB,2D

echo "[TUTORIAL-RUNNER] showing reported data ..."
docker exec -it "$CONTAINER_NAME" bash -c "flexmeasures show beliefs --sensor ${FM_TOY_PROCESS_INFLEXIBLE_COST_SENSOR_ID} --start ${TOMORROW}T00:00:00+01:00 --duration PT24H"


echo "[TUTORIAL-RUNNER] now the breakable process ..."

echo "
{
    'input': [{'sensor': ${FM_TOY_PROCESS_BREAKABLE_SENSOR_ID}}],
    'output': [{'sensor': ${FM_TOY_PROCESS_BREAKABLE_COST_SENSOR_ID}}]
}" > breakable-parameters.json

docker cp breakable-parameters.json "$CONTAINER_NAME":/app

docker exec -it "$CONTAINER_NAME" flexmeasures add report --source "$FM_TOY_PROFIT_OR_LOSS_REPORTER_SOURCE_ID" \
   --parameters breakable-parameters.json \
   --start-offset DB,1D --end-offset DB,2D

echo "[TUTORIAL-RUNNER] showing reported data ..."
docker exec -it "$CONTAINER_NAME" bash -c "flexmeasures show beliefs --sensor ${FM_TOY_PROCESS_BREAKABLE_COST_SENSOR_ID} --start ${TOMORROW}T00:00:00+01:00 --duration PT24H"



echo "[TUTORIAL-RUNNER] now the shiftable process ..."

echo "
{
    'input' : [{'sensor': ${FM_TOY_PROCESS_SHIFTABLE_SENSOR_ID}}],
    'output' : [{'sensor': ${FM_TOY_PROCESS_SHIFTABLE_COST_SENSOR_ID}}]
}" > shiftable-parameters.json

docker cp shiftable-parameters.json "$CONTAINER_NAME":/app

docker exec -it "$CONTAINER_NAME" flexmeasures add report --source "$FM_TOY_PROFIT_OR_LOSS_REPORTER_SOURCE_ID" \
   --parameters shiftable-parameters.json \
   --start-offset DB,1D --end-offset DB,2D

echo "[TUTORIAL-RUNNER] showing reported data ..."
docker exec -it "$CONTAINER_NAME" bash -c "flexmeasures show beliefs --sensor ${FM_TOY_PROCESS_SHIFTABLE_COST_SENSOR_ID} --start ${TOMORROW}T00:00:00+01:00 --duration PT24H"
