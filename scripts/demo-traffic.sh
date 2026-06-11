#!/usr/bin/env bash
# Rebuild backend + generate enough traffic so all Grafana panels light up.
# Usage: bash scripts/demo-traffic.sh

set -e

BASE_URL="${BASE_URL:-http://localhost:8000}"
ADMIN_USER="${ADMIN_USER:-admin}"
ADMIN_PASS="${ADMIN_PASS:-admin123}"

cd "$(dirname "$0")/.."

echo ""
echo "============================================================"
echo "  SSMS demo traffic generator"
echo "============================================================"
echo ""

echo "[1/6] Rebuild backend image..."
docker compose build backend
echo ""

echo "[2/6] Recreate backend container..."
docker compose up -d --force-recreate --wait backend
sleep 3
echo ""

echo "[3/6] Verify counters are exposed..."
curl -s "${BASE_URL}/metrics" | grep -E "^sales_total |^orders_total |^revenue_total |^barcode_scans_total |^successful_logins_total |^soc_alerts_total{|^quarantine_state" | head -8
echo ""

echo "[4/6] Login as admin (increments successful_logins_total)..."
TOKEN=$(curl -s -X POST "${BASE_URL}/auth/login" \
    -d "username=${ADMIN_USER}&password=${ADMIN_PASS}" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    | python3 -c "import json,sys;print(json.load(sys.stdin)['access_token'])")
echo "  Got token (length: ${#TOKEN})"
echo ""

echo "[5/6] Generate business traffic..."
echo "  -> Create 5 sales..."
for i in 1 2 3 4 5; do
    curl -s -X POST "${BASE_URL}/sales/" \
        -H "Authorization: Bearer ${TOKEN}" \
        -H "Content-Type: application/json" \
        -d "{\"cashier\":\"admin\",\"status\":\"completed\",\"items\":[{\"product_name\":\"DemoItem-${i}\",\"quantity\":${i},\"unit_price\":2.50}]}" \
        > /dev/null
done

echo "  -> Create 3 web orders..."
for i in 1 2 3; do
    curl -s -X POST "${BASE_URL}/orders/" \
        -H "Content-Type: application/json" \
        -d "{\"items\":[{\"product_name\":\"Apple\",\"quantity\":2}]}" \
        > /dev/null
done

echo "  -> Trigger 5 failed logins (auth_flood)..."
for i in 1 2 3 4 5 6 7; do
    curl -s -X POST "${BASE_URL}/auth/login" \
        -d "username=admin&password=BADPASS${i}" \
        -H "Content-Type: application/x-www-form-urlencoded" \
        > /dev/null
done

echo "  -> Scan 4 known barcodes..."
for code in "2000000000015" "2000000000022" "2000000000039" "2000000000046"; do
    curl -s -X POST "${BASE_URL}/stock/scan/${code}?action=sell" \
        -H "Authorization: Bearer ${TOKEN}" \
        > /dev/null
done

echo "  -> Scan 2 unknown barcodes..."
for code in "9999999999991" "9999999999992"; do
    curl -s -X POST "${BASE_URL}/stock/scan/${code}?action=sell" \
        -H "Authorization: Bearer ${TOKEN}" \
        > /dev/null
done
echo ""

echo "[6/6] Snapshot counters after traffic..."
sleep 2
curl -s "${BASE_URL}/metrics" | grep -E "^sales_total |^orders_total |^confirmed_orders_total |^revenue_total |^barcode_scans_total |^barcode_sell_operations_total |^successful_logins_total |^failed_logins_total |^quarantine_state |^quarantine_trigger_total " | head -15
echo ""

echo "============================================================"
echo "  Done. Open Grafana now."
echo "  http://localhost:3000/d/ssms-soc-overview"
echo ""
echo "  Wait ~10 seconds for Prometheus to scrape, then refresh."
echo "  All panels should now have data."
echo "============================================================"
