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
SMOKE_KEY="_dev-stack-smoke/$$-$(date +%s).txt"
SMOKE_FILE="$(mktemp "${TMPDIR:-/tmp}/datenportal-garage-smoke.XXXXXX")"
SMOKE_TEXT="Datenportal Garage smoke test"

cleanup() {
  docker compose --profile tools run --rm aws \
    s3api delete-object --bucket ch.so.daten --key "${SMOKE_KEY}" >/dev/null 2>&1 || true
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

echo "Checking anonymous public GET ..."
downloaded="$(curl --fail --silent --show-error "${PUBLIC_URL}/${SMOKE_KEY}")"
if [[ "${downloaded}" != "${SMOKE_TEXT}" ]]; then
  echo "Public object content did not match the uploaded content." >&2
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

echo "Garage, Datenblatt-Editor and Jenkins smoke tests passed."
