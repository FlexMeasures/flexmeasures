
echo "[TUTORIAL-RUNNER] RUNNING TUTORIAL 3 (PV CURTAILMENT / MORE THAN ONE FLEXIBLE ASSET) ..."
echo "----------------------------------------------------------------------------------------"


TOMORROW=$(date --date="next day" '+%Y-%m-%d')

echo "[TUTORIAL-RUNNER] Curtailing PV in flex-model ..."

docker exec -it flexmeasures-server-1 flexmeasures add schedule --asset 2 \
  --start ${TOMORROW}T07:00+00:00 --duration PT12H \
  --flex-model '[{"sensor": 2, "soc-at-start": "225 kWh", "soc-min": "50 kWh"}, {"sensor": 3, "consumption-capacity": "0 kW", "production-capacity": {"sensor": 3}, "soc-at-start": "225 kWh"}]'

echo "[TUTORIAL-RUNNER] showing schedule ..."
docker exec -it flexmeasures-server-1 flexmeasures show beliefs --sensor 2 --start ${TOMORROW}T07:00:00+00:00 --duration PT12H
