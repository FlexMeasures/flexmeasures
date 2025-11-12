
echo "[TUTORIAL-RUNNER] RUNNING TUTORIAL 3 (PV CURTAILMENT / MORE THAN ONE FLEXIBLE ASSET) ..."
echo "----------------------------------------------------------------------------------------"


TOMORROW=$(date --date="next day" '+%Y-%m-%d')

echo "[TUTORIAL-RUNNER] Re-computing schedule with curtailment asset added ..."

docker exec -it flexmeasures-server-1 flexmeasures add schedule --sensor 3 \
  --start ${TOMORROW}T07:00+00:00 --duration PT12H \
  --flex-model '{"consumption-capacity": "0 kW", "production-capacity": {"sensor": 3}, "soc-at-start": "1kWh"}'\
  --flex-context '{"production-price": [{"start": "2025-11-12T00:07+00", "duration": "PT5H", "value": "4 EUR/MWh"}, {"start": "2025-11-12T12:00+00", "duration": "PT2H", "value": "-10 EUR/MWh"}, {"start": "2025-11-12T14:00+00", "duration": "PT5H", "value": "4 EUR/MWh"}]}'
#
#docker exec -it flexmeasures-server-1 flexmeasures add schedule --asset 2 \
#  --start ${TOMORROW}T07:00+00:00 --duration PT12H \
#  --flex-model '[{"sensor": 3, "consumption-capacity": "0 kW", "production-capacity": {"sensor": 3}}]'\
#  --flex-context '{"production-price": [{"start": "2025-11-12T00:00+00", "duration": "PT12H", "value": "4 EUR/MWh"}, {"start": "2025-11-12T12:00+00", "duration": "PT2H", "value": "-10 EUR/MWh"}, {"start": "2025-11-12T14:00+00", "duration": "PT10H", "value": "4 EUR/MWh"}]}'
#--flex-model '[{"sensor": 2, "soc-at-start": "223 kWh", "soc-min": "50 kWh"}, {"sensor": 3, "consumption-capacity": "0 kW", "production-capacity": {"sensor": 3}}]'\
#--flex-context '{"production-price": "0 EUR/kWh"}'

echo "[TUTORIAL-RUNNER] showing battery and PV schedules ..."
docker exec -it flexmeasures-server-1 flexmeasures show beliefs --sensor 2 --sensor 3 --start ${TOMORROW}T07:00:00+00:00 --duration PT12H

# echo "[TUTORIAL-RUNNER] showing PV schedule ..."
# docker exec -it flexmeasures-server-1 flexmeasures show beliefs --sensor 3 --start ${TOMORROW}T07:00:00+00:00 --duration PT12H