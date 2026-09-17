#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_DIR}"

if [[ ! -f .env || ! -f services/garage/garage.toml ]]; then
  echo "Run ./scripts/init.sh and ./scripts/up.sh first." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

PUBLIC_PORT="${GARAGE_PUBLIC_PORT:-8081}"
PUBLIC_URL="http://localhost:${PUBLIC_PORT}/ch.so.daten"
EDITOR_URL="http://localhost:${PUBLIC_PORT}/metadaten-editor"
JENKINS_URL="http://localhost:${JENKINS_PORT:-8080}"
SODATA_URL="http://localhost:${SODATA_PORT:-8082}"
SMOKE_KEY="_dev-stack-smoke/$$-$(date +%s).txt"
SMOKE_NAME="${SMOKE_KEY##*/}"
ROOT_SMOKE_KEY="_dev-stack-smoke-$$-$(date +%s).txt"
DENIED_KEY="_dev-stack-smoke/denied-$$-$(date +%s).txt"
SMOKE_FILE="$(mktemp "${TMPDIR:-/tmp}/datenportal-garage-smoke.XXXXXX")"
SMOKE_TEXT="Datenportal Garage smoke test"
website_disabled=false

: "${GARAGE_BROWSER_ACCESS_KEY:?Run ./scripts/init.sh first}"
: "${GARAGE_BROWSER_SECRET_KEY:?Run ./scripts/init.sh first}"

browser_aws() {
  docker compose --profile tools run \
    --rm \
    --no-deps \
    -e AWS_ACCESS_KEY_ID="${GARAGE_BROWSER_ACCESS_KEY}" \
    -e AWS_SECRET_ACCESS_KEY="${GARAGE_BROWSER_SECRET_KEY}" \
    aws "$@"
}

cleanup() {
  if [[ "${website_disabled}" == true ]]; then
    docker compose run --rm garage-init >/dev/null
  fi
  docker compose --profile tools run --rm aws \
    s3api delete-object --bucket ch.so.daten --key "${SMOKE_KEY}" >/dev/null 2>&1 || true
  docker compose --profile tools run --rm aws \
    s3api delete-object --bucket ch.so.daten --key "${ROOT_SMOKE_KEY}" >/dev/null 2>&1 || true
  docker compose --profile tools run --rm aws \
    s3api delete-object --bucket ch.so.daten --key "${DENIED_KEY}" >/dev/null 2>&1 || true
  rm -f "${SMOKE_FILE}"
}
trap cleanup EXIT

printf '%s\n' "${SMOKE_TEXT}" > "${SMOKE_FILE}"

echo "Checking bucket existence ..."
docker compose --profile tools run --rm aws \
  s3api head-bucket --bucket ch.so.daten >/dev/null

echo "Checking authenticated S3 upload ..."
docker compose --profile tools run --rm \
  -v "${SMOKE_FILE}:/tmp/smoke-object:ro" \
  aws s3 cp /tmp/smoke-object "s3://ch.so.daten/${SMOKE_KEY}" >/dev/null
docker compose --profile tools run --rm \
  -v "${SMOKE_FILE}:/tmp/smoke-object:ro" \
  aws s3 cp /tmp/smoke-object "s3://ch.so.daten/${ROOT_SMOKE_KEY}" >/dev/null

echo "Checking browser key read access ..."
browser_aws s3api list-objects-v2 \
  --bucket ch.so.daten \
  --prefix "${SMOKE_KEY}" \
  --query 'Contents[0].Key' \
  --output text | grep -Fxq "${SMOKE_KEY}"

browser_downloaded="$(browser_aws s3 cp "s3://ch.so.daten/${SMOKE_KEY}" -)"
if [[ "${browser_downloaded}" != "${SMOKE_TEXT}" ]]; then
  echo "Browser key could not download the uploaded test object." >&2
  exit 1
fi

echo "Checking browser key write denial ..."
if docker compose --profile tools run \
  --rm \
  --no-deps \
  -e AWS_ACCESS_KEY_ID="${GARAGE_BROWSER_ACCESS_KEY}" \
  -e AWS_SECRET_ACCESS_KEY="${GARAGE_BROWSER_SECRET_KEY}" \
  -v "${SMOKE_FILE}:/tmp/browser-write:ro" \
  aws s3 cp /tmp/browser-write "s3://ch.so.daten/${DENIED_KEY}" >/dev/null 2>&1; then
  echo "Browser key unexpectedly allowed an S3 upload." >&2
  exit 1
fi

if browser_aws s3api delete-object \
  --bucket ch.so.daten \
  --key "${SMOKE_KEY}" >/dev/null 2>&1; then
  echo "Browser key unexpectedly allowed an S3 delete." >&2
  exit 1
fi

echo "Checking anonymous public GET ..."
downloaded="$(curl --fail --silent --show-error "${PUBLIC_URL}/${SMOKE_KEY}")"
if [[ "${downloaded}" != "${SMOKE_TEXT}" ]]; then
  echo "Public object content did not match the uploaded content." >&2
  exit 1
fi

echo "Checking anonymous directory browsing ..."
root_listing_html=""
for _ in {1..15}; do
  root_listing_html="$(curl --fail --silent --show-error "${PUBLIC_URL}/")"
  if grep -Fq '_dev-stack-smoke/' <<<"${root_listing_html}" && \
    grep -Fq "${ROOT_SMOKE_KEY}" <<<"${root_listing_html}"; then
    break
  fi
  sleep 1
done
if ! grep -Fq '_dev-stack-smoke/' <<<"${root_listing_html}" || \
  ! grep -Fq "${ROOT_SMOKE_KEY}" <<<"${root_listing_html}"; then
  echo "Public browser root did not contain the test folder and root object." >&2
  exit 1
fi

listing_html=""
for _ in {1..15}; do
  listing_html="$(curl --fail --silent --show-error "${PUBLIC_URL}/_dev-stack-smoke/")"
  if grep -Fq "${SMOKE_NAME}" <<<"${listing_html}"; then
    break
  fi
  sleep 1
done
if ! grep -Fq "${SMOKE_NAME}" <<<"${listing_html}"; then
  echo "Public browser listing did not contain the uploaded test object." >&2
  exit 1
fi

echo "Checking browser HTTP write denial ..."
put_status="$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
  -X PUT \
  --data-binary "@${SMOKE_FILE}" \
  "${PUBLIC_URL}/${DENIED_KEY}")"
if [[ "${put_status}" == 2* ]]; then
  echo "Public browser unexpectedly accepted an HTTP upload." >&2
  exit 1
fi

echo "Checking public HEAD ..."
curl --fail --silent --show-error --head "${PUBLIC_URL}/${SMOKE_KEY}" >/dev/null

echo "Checking CORS preflight ..."
cors_headers="$(curl --fail --silent --show-error --dump-header - --output /dev/null \
  -X OPTIONS \
  -H 'Origin: http://localhost:8080' \
  -H 'Access-Control-Request-Method: GET' \
  "${PUBLIC_URL}/${SMOKE_KEY}")"
if ! grep -qi '^Access-Control-Allow-Origin: \*' <<<"${cors_headers}"; then
  echo "CORS response did not contain Access-Control-Allow-Origin: *." >&2
  exit 1
fi

echo "Checking that private website state blocks the browser ..."
docker compose exec -T garage \
  /garage bucket website --deny ch.so.daten >/dev/null
website_disabled=true
private_status="$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
  "${PUBLIC_URL}/")"
if [[ "${private_status}" == 2* ]]; then
  echo "Public browser remained accessible after website access was disabled." >&2
  exit 1
fi
docker compose run --rm garage-init >/dev/null
website_disabled=false
curl --fail --silent --show-error "${PUBLIC_URL}/" -o /dev/null

echo "Checking Datenblatt-Editor start page ..."
editor_html="$(curl --fail --silent --show-error "${EDITOR_URL}/")"
if ! grep -q '<base href="/metadaten-editor/">' <<<"${editor_html}"; then
  echo "Editor response did not contain the expected public base path." >&2
  exit 1
fi

echo "Checking Datenblatt-Editor deep link ..."
deep_link_html="$(curl --fail --silent --show-error "${EDITOR_URL}/draft/smoke-test")"
if ! grep -q '<base href="/metadaten-editor/">' <<<"${deep_link_html}"; then
  echo "Editor deep link did not contain the expected public base path." >&2
  exit 1
fi

echo "Checking Datenblatt-Editor HEAD ..."
curl --fail --silent --show-error --head "${EDITOR_URL}/" >/dev/null

echo "Checking Datenblatt-Editor CORS preflight ..."
editor_cors_headers="$(curl --fail --silent --show-error --dump-header - --output /dev/null \
  -X OPTIONS \
  -H 'Origin: http://localhost:8080' \
  -H 'Access-Control-Request-Method: GET' \
  "${EDITOR_URL}/")"
if ! grep -qi '^Access-Control-Allow-Origin: \*' <<<"${editor_cors_headers}"; then
  echo "Editor CORS response did not contain Access-Control-Allow-Origin: *." >&2
  exit 1
fi

echo "Checking Datenblatt-Editor static source ..."
curl --fail --silent --show-error \
  "${EDITOR_URL}/mock-sources/dataset.index.xtf" \
  -o /dev/null

editor_asset="$(sed -n 's/.*src="\([^"[:space:]]*assets\/[^"[:space:]]*\)".*/\1/p' <<<"${editor_html}" | head -n 1)"
if [[ -z "${editor_asset}" ]]; then
  echo "Could not find an editor asset in the HTML response." >&2
  exit 1
fi
editor_asset="${editor_asset#./}"
curl --fail --silent --show-error "${EDITOR_URL}/${editor_asset}" -o /dev/null

echo "Checking public downloads from Jenkins ..."
docker compose exec -T jenkins curl --fail --silent --show-error "${PUBLIC_URL}/${SMOKE_KEY}" -o /dev/null

echo "Checking Portal (sodata) ..."
if curl --fail --silent --show-error --max-time 5 "${PUBLIC_URL}/current.json" >/dev/null 2>&1; then
  echo "Checking Portal health ..."
  curl --fail --silent --show-error "${SODATA_URL}/actuator/health" -o /dev/null

  echo "Checking Portal start page ..."
  curl --fail --silent --show-error "${SODATA_URL}/" -o /dev/null

  echo "Checking Portal DuckDB artifact ..."
  python3 - "${PUBLIC_URL}" "${SODATA_URL}" <<'PYTHON'
import hashlib, json, sys, urllib.request
sys.path.insert(0, 'scripts/testing')
from importlib import import_module
validate = import_module('check-publication-manifest').validate
with urllib.request.urlopen(sys.argv[1] + '/current.json') as response:
    manifest = validate(json.load(response))
with urllib.request.urlopen(sys.argv[1] + '/' + manifest['duckdb']) as response:
    published = response.read()
with urllib.request.urlopen(sys.argv[2] + '/catalog/catalog.duckdb') as response:
    active = response.read()
assert published == active, 'Portal DuckDB differs from the published generation; reload required'
assert active[8:12] == b'DUCK'
with urllib.request.urlopen(sys.argv[2] + '/catalog/catalog.duckdb?v=' + hashlib.sha256(active).hexdigest()) as response:
    assert response.read() == active
PYTHON
else
  echo "Skipping Portal (sodata) checks: current.json is not published yet."
fi

echo "Checking Jenkins login endpoint ..."
curl --fail --silent --show-error "${JENKINS_URL}/login" -o /dev/null

echo "Checking authenticated Jenkins API ..."
jenkins_api="$(curl --fail --silent --show-error \
  --user 'admin:admin' \
  "${JENKINS_URL}/api/json")"
if ! grep -q '"numExecutors"' <<<"${jenkins_api}"; then
  echo "Jenkins API response did not contain the expected controller data." >&2
  exit 1
fi

echo "Garage, S3 browser, Datenblatt-Editor, Portal and Jenkins smoke tests passed."
