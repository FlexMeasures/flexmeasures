
echo "[TUTORIAL-RUNNER] RUNNING TUTORIAL 3 (PV CURTAILMENT / MORE THAN ONE FLEXIBLE ASSET) ..."
echo "----------------------------------------------------------------------------------------"


TOMORROW=$(date --date="next day" '+%Y-%m-%d')

echo "[TUTORIAL-RUNNER] Computing schedule for PV curtailment (using artificial price profile) ..."

echo '''{
  "consumption-price": [
    {"start": "'${TOMORROW}'T00:00+00", "duration": "PT24H", "value": "10 EUR/MWh"}
  ],
  "production-price": [
    {"start": "'${TOMORROW}'T05:00+00", "duration": "PT7H", "value": "4 EUR/MWh"},
    {"start": "'${TOMORROW}'T12:00+00", "duration": "PT2H", "value": "-10 EUR/MWh"},
    {"start": "'${TOMORROW}'T14:00+00", "duration": "PT7H", "value": "4 EUR/MWh"}
  ]
}''' > tutorial3-priceprofile-flex-context.json
docker cp tutorial3-priceprofile-flex-context.json flexmeasures-server-1:/app/ 

# Running only the PV sensor
docker exec -it flexmeasures-server-1 flexmeasures add schedule --sensor 3 \
  --start ${TOMORROW}T07:00+00:00 --duration PT12H \
  --flex-model '{"consumption-capacity": "0 kW", "production-capacity": {"sensor": 3, "source": 4}}'\
  --flex-context tutorial3-priceprofile-flex-context.json 
echo "[TUTORIAL-RUNNER] showing PV schedule ..."
docker exec -it flexmeasures-server-1 flexmeasures show beliefs --sensor 3 --start ${TOMORROW}T07:00:00+00:00 --duration PT12H

echo "[TUTORIAL-RUNNER] Cleaning solar data for the next steps ..."
# remove all previous beliefs on PV sensor so we don't have schedules mixed in the next run (issue 1807 can help with this, so selection by source works)
docker exec -it flexmeasures-server-1 flexmeasures delete beliefs --sensor 3 --force
docker exec -it flexmeasures-server-1 flexmeasures add beliefs --sensor 3 --source 4 /app/solar-tomorrow.csv --timezone Europe/Amsterdam

echo "[TUTORIAL-RUNNER] Now running both battery and PV together, still using block price profiles ..."
docker exec -it flexmeasures-server-1 flexmeasures add schedule --asset 2 \
  --start ${TOMORROW}T07:00+00:00 --duration PT12H \
  --flex-model '[{"sensor": 3, "consumption-capacity": "0 kW", "production-capacity": {"sensor": 3, "source": 4}}, {"sensor": 2, "soc-at-start": "225 kWh", "soc-min": "50 kWh"}]'\
  --flex-context tutorial3-priceprofile-flex-context.json 

echo "[TUTORIAL-RUNNER] showing PV and battery schedule ..."
docker exec -it flexmeasures-server-1 flexmeasures show beliefs --sensor 3 --sensor 2 --start ${TOMORROW}T07:00:00+00:00 --duration PT12H

docker exec -it flexmeasures-server-1 flexmeasures delete beliefs --sensor 3 --force
docker exec -it flexmeasures-server-1 flexmeasures add beliefs --sensor 3 --source 4 /app/solar-tomorrow.csv --timezone Europe/Amsterdam

echo "[TUTORIAL-RUNNER] Now running both battery and PV together, with realistic DA prices and larger battery ..."
docker exec -it flexmeasures-server-1 flexmeasures add schedule --asset 2 \
  --start ${TOMORROW}T07:00+00:00 --duration PT12H \
  --flex-model '[{"sensor": 3, "consumption-capacity": "0 kW", "production-capacity": {"sensor": 3, "source": 4}}, {"sensor": 2, "soc-at-start": "225 kWh", "soc-min": "50 kWh", "soc-max": "900kWh"}]'

echo "[TUTORIAL-RUNNER] showing PV and battery schedule ..."
docker exec -it flexmeasures-server-1 flexmeasures show beliefs --sensor 3 --sensor 2 --start ${TOMORROW}T07:00:00+00:00 --duration PT12H
