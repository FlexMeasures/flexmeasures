#!/usr/bin/env bash

set -euo pipefail

CONTAINER_NAME="${1:-$(basename "$(pwd)")-server-1}"
CLIENT_REQUIREMENT="flexmeasures-client>=0.9.4,<0.10"

echo "[TUTORIAL-RUNNER] RUNNING DATA-INGESTION TUTORIAL ..."
echo "-----------------------------------------------------"

if ! command -v uv >/dev/null 2>&1; then
    echo "The data-ingestion runner requires uv: https://docs.astral.sh/uv/" >&2
    exit 1
fi

curl --fail --silent --show-error \
    --retry 30 --retry-delay 1 --retry-all-errors \
    "http://localhost:5000/api/v3_0/health/ready" >/dev/null

if [[ -z "${FM_TOY_BATTERY_SENSOR_ID:-}" ]]; then
    eval "$(docker exec -i "${CONTAINER_NAME}" flexmeasures add toy-account \
        --kind battery --shell-vars | grep '^FM_TOY_')"
fi

if [[ -n "${FLEXMEASURES_CLIENT_PROJECT:-}" ]]; then
    CLIENT_COMMAND=(uv run --project "${FLEXMEASURES_CLIENT_PROJECT}")
else
    CLIENT_COMMAND=(uv run --no-project --with "${CLIENT_REQUIREMENT}")
fi

FLEXMEASURES_SENSOR_ID="${FM_TOY_BATTERY_SENSOR_ID}" \
FLEXMEASURES_SENSOR_UNIT="MW" \
FLEXMEASURES_SENSOR_RESOLUTION="PT1H" \
    "${CLIENT_COMMAND[@]}" python \
    documentation/tut/scripts/run-data-ingestion.py
