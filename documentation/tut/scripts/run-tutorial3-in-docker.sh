
echo "[TUTORIAL-RUNNER] RUNNING TUTORIAL 3 (PV CURTAILMENT / MORE THAN ONE FLEXIBLE ASSET) ..."
echo "----------------------------------------------------------------------------------------"


echo "[TUTORIAL-RUNNER] Curtailing PV in flex-model ..."

docker exec -it flexmeasures-server-1 flexmeasures add schedule --sensor 2 \
  --start ${TOMORROW}T07:00+01:00 --duration PT12H --soc-at-start 50% \
  --flex-model '[{"sensor": 2, "roundtrip-efficiency": "90%"}, {"sensor": 3, "consumption-capacity": "0 kW", "production-capacity": {"sensor": 3}}]'

echo "[TUTORIAL-RUNNER] showing schedule ..."
docker exec -it flexmeasures-server-1 flexmeasures show beliefs --sensor 2 --start ${TOMORROW}T07:00:00+01:00 --duration PT12H
