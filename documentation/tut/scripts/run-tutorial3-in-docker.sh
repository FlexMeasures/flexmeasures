
#!/bin/bash

# Determine container name: use $1 if provided, otherwise construct from current folder name
CONTAINER_NAME="${1:-$(basename $(pwd))-server-1}"

echo "[TUTORIAL-RUNNER] RUNNING TUTORIAL 3 (PV CURTAILMENT / MORE THAN ONE FLEXIBLE ASSET) ..."
echo "----------------------------------------------------------------------------------------"

eval "$(docker exec -i $CONTAINER_NAME flexmeasures add toy-account --kind battery --shell-vars | grep '^FM_TOY_')"

TOMORROW=$(date --date="next day" '+%Y-%m-%d')

echo "[TUTORIAL-RUNNER] Computing schedule for PV curtailment (using artificial price profile) ..."

echo '''{
  "consumption-price": [
    {"start": "'${TOMORROW}'T00:00+01", "duration": "PT24H", "value": "10 EUR/MWh"}
  ],
  "production-price": [
    {"start": "'${TOMORROW}'T05:00+01", "duration": "PT7H", "value": "4 EUR/MWh"},
    {"start": "'${TOMORROW}'T12:00+01", "duration": "PT2H", "value": "-10 EUR/MWh"},
    {"start": "'${TOMORROW}'T14:00+01", "duration": "PT7H", "value": "4 EUR/MWh"}
  ]
}''' > tutorial3-priceprofile-flex-context.json
docker cp tutorial3-priceprofile-flex-context.json $CONTAINER_NAME:/app/ 

# Running only the PV sensor
docker exec -it $CONTAINER_NAME flexmeasures add schedule --sensor ${FM_TOY_SOLAR_SENSOR_ID} \
  --start ${TOMORROW}T07:00+01:00 --duration PT12H \
  --flex-model '{"consumption-capacity": "0 kW", "production-capacity": {"sensor": '"${FM_TOY_SOLAR_SENSOR_ID}"', "source": 4}}'\
  --flex-context tutorial3-priceprofile-flex-context.json 
echo "[TUTORIAL-RUNNER] showing PV schedule ..."
docker exec -it $CONTAINER_NAME flexmeasures show beliefs --sensor ${FM_TOY_SOLAR_SENSOR_ID} --start ${TOMORROW}T07:00:00+01:00 --duration PT12H

echo "[TUTORIAL-RUNNER] Cleaning solar data for the next steps ..."
# remove all previous beliefs on PV sensor so we don't have schedules mixed in the next run (issue 1807 can help with this, so selection by source works)
docker exec -it $CONTAINER_NAME flexmeasures delete beliefs --sensor ${FM_TOY_SOLAR_SENSOR_ID} --force
docker exec -it $CONTAINER_NAME flexmeasures add beliefs --sensor ${FM_TOY_SOLAR_SENSOR_ID} --source 4 /app/solar-tomorrow.csv --timezone Europe/Amsterdam

echo "[TUTORIAL-RUNNER] Now running both battery and PV together, still using block price profiles ..."
docker exec -it $CONTAINER_NAME flexmeasures add schedule --asset ${FM_TOY_BUILDING_ASSET_ID} \
  --start ${TOMORROW}T07:00+01:00 --duration PT12H \
  --flex-model '[{"sensor": '"${FM_TOY_SOLAR_SENSOR_ID}"', "consumption-capacity": "0 kW", "production-capacity": {"sensor": '"${FM_TOY_SOLAR_SENSOR_ID}"', "source": 4}}, {"sensor": '"${FM_TOY_BATTERY_SENSOR_ID}"', "soc-at-start": "225 kWh", "soc-min": "50 kWh"}]'\
  --flex-context tutorial3-priceprofile-flex-context.json 

echo "[TUTORIAL-RUNNER] showing PV and battery schedule ..."
docker exec -it $CONTAINER_NAME flexmeasures show beliefs --sensor ${FM_TOY_SOLAR_SENSOR_ID} --sensor ${FM_TOY_BATTERY_SENSOR_ID} --start ${TOMORROW}T07:00:00+01:00 --duration PT12H

docker exec -it $CONTAINER_NAME flexmeasures delete beliefs --sensor ${FM_TOY_SOLAR_SENSOR_ID} --force
docker exec -it $CONTAINER_NAME flexmeasures add beliefs --sensor ${FM_TOY_SOLAR_SENSOR_ID} --source 4 /app/solar-tomorrow.csv --timezone Europe/Amsterdam

echo "[TUTORIAL-RUNNER] Now running both battery and PV together, with realistic DA prices and larger battery ..."
docker exec -it $CONTAINER_NAME flexmeasures add schedule --asset ${FM_TOY_BUILDING_ASSET_ID} \
  --start ${TOMORROW}T07:00+01:00 --duration PT12H \
  --flex-model '[{"sensor": '"${FM_TOY_SOLAR_SENSOR_ID}"', "consumption-capacity": "0 kW", "production-capacity": {"sensor": '"${FM_TOY_SOLAR_SENSOR_ID}"', "source": 4}}, {"sensor": '"${FM_TOY_BATTERY_SENSOR_ID}"', "soc-at-start": "225 kWh", "soc-min": "50 kWh", "soc-max": "900kWh"}]'

echo "[TUTORIAL-RUNNER] showing PV and battery schedule ..."
docker exec -it $CONTAINER_NAME flexmeasures show beliefs --sensor ${FM_TOY_SOLAR_SENSOR_ID} --sensor ${FM_TOY_BATTERY_SENSOR_ID} --start ${TOMORROW}T07:00:00+01:00 --duration PT12H
