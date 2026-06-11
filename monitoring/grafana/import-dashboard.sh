#!/usr/bin/env bash
# Imports the SSMS dashboard into Grafana via the REST API.
# Works around the Grafana 13 unified-storage provisioning quirks.

set -euo pipefail

GRAFANA_URL="${GRAFANA_URL:-http://localhost:3000}"
GRAFANA_USER="${GRAFANA_USER:-admin}"
GRAFANA_PASS="${GRAFANA_PASS:-admin}"
DASHBOARD_FILE="${DASHBOARD_FILE:-monitoring/grafana/dashboards/ssms-soc-overview.json}"

echo "[ssms] Waiting for Grafana to be reachable..."
for i in {1..30}; do
    if curl -sf "${GRAFANA_URL}/api/health" >/dev/null 2>&1; then
        echo "[ssms] Grafana is up."
        break
    fi
    sleep 1
done

if ! [ -f "${DASHBOARD_FILE}" ]; then
    echo "[ssms] ERR dashboard file not found: ${DASHBOARD_FILE}" >&2
    exit 1
fi

echo "[ssms] Ensuring Prometheus datasource exists..."
DS_PAYLOAD='{
  "name": "Prometheus",
  "uid": "prometheus",
  "type": "prometheus",
  "access": "proxy",
  "url": "http://prometheus:9090",
  "isDefault": true,
  "jsonData": { "timeInterval": "5s" }
}'

curl -sf -u "${GRAFANA_USER}:${GRAFANA_PASS}" \
    -X POST "${GRAFANA_URL}/api/datasources" \
    -H "Content-Type: application/json" \
    -d "${DS_PAYLOAD}" >/dev/null 2>&1 || \
curl -sf -u "${GRAFANA_USER}:${GRAFANA_PASS}" \
    -X PUT "${GRAFANA_URL}/api/datasources/uid/prometheus" \
    -H "Content-Type: application/json" \
    -d "${DS_PAYLOAD}" >/dev/null 2>&1 || true

echo "[ssms] Importing dashboard to General folder..."
PAYLOAD=$(python3 - << PYEOF
import json
with open("${DASHBOARD_FILE}", "r") as f:
    dash = json.load(f)
dash["id"] = None
print(json.dumps({
    "dashboard": dash,
    "overwrite": True,
    "message": "imported via SSMS init script"
}))
PYEOF
)

RESPONSE=$(curl -s -u "${GRAFANA_USER}:${GRAFANA_PASS}" \
    -X POST "${GRAFANA_URL}/api/dashboards/db" \
    -H "Content-Type: application/json" \
    -d "${PAYLOAD}")

echo "[ssms] Response: ${RESPONSE}"
if echo "${RESPONSE}" | grep -q '"status":"success"'; then
    URL=$(echo "${RESPONSE}" | python3 -c "import json,sys;print(json.load(sys.stdin).get('url',''))")
    echo "[ssms] OK dashboard imported : ${GRAFANA_URL}${URL}"
else
    echo "[ssms] WARN unexpected response. Check Grafana UI manually."
fi
