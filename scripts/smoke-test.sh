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
EDITOR_URL="http://localhost:${PUBLIC_PORT}/datenblatt-editor"
JENKINS_URL="http://localhost:${PUBLIC_PORT}/jenkins"
SODATA_URL="http://localhost:${PUBLIC_PORT}"
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

echo "Checking public Range ..."
range_status="$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' -H 'Range: bytes=0-3' "${PUBLIC_URL}/${SMOKE_KEY}")"
[[ "$range_status" == 206 ]] || { echo "Range returned $range_status, expected 206" >&2; exit 1; }
python3 - "${PUBLIC_URL}/${SMOKE_KEY}" <<'PYTHON'
import sys, urllib.request
request = urllib.request.Request(sys.argv[1], headers={'Range': 'bytes=0-3', 'Origin': 'https://daten.so.ch'})
with urllib.request.urlopen(request) as response:
    assert response.read() == b'Date'
    assert response.headers['Content-Range'].startswith('bytes 0-3/')
    assert response.headers['Access-Control-Allow-Origin'] == '*'
    assert 'content-range' in response.headers['Access-Control-Expose-Headers'].lower()
PYTHON


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
bucket_headers="$(curl --fail --silent --show-error --head "${PUBLIC_URL}/${SMOKE_KEY}")"
if ! grep -qi '^Cache-Control: no-store' <<<"${bucket_headers}"; then
  echo "Bucket response did not contain Cache-Control: no-store." >&2
  exit 1
fi

echo "Checking bucket root redirect ..."
bucket_redirect_headers="$(curl --silent --show-error --dump-header - --output /dev/null \
  --write-out '\n%{http_code}' "${PUBLIC_URL}")"
if [[ "${bucket_redirect_headers##*$'\n'}" != 308 ]] || \
  ! grep -Fqi 'Location: /ch.so.daten/' <<<"${bucket_redirect_headers}"; then
  echo "Bucket root did not redirect to its slash URL: ${bucket_redirect_headers}" >&2
  exit 1
fi

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

python3 "$SCRIPT_DIR/test-docs-gateway.py" --base-url "$SODATA_URL"

echo "Checking Datenblatt-Editor start page ..."
editor_redirect_headers="$(curl --silent --show-error --dump-header - --output /dev/null \
  --write-out '\n%{http_code}' "${EDITOR_URL}")"
if [[ "${editor_redirect_headers##*$'\n'}" != 308 ]] || \
  ! grep -Fqi 'Location: /datenblatt-editor/' <<<"${editor_redirect_headers}"; then
  echo "Editor root did not redirect to its slash URL: ${editor_redirect_headers}" >&2
  exit 1
fi
editor_html="$(curl --fail --silent --show-error "${EDITOR_URL}/")"
if ! grep -q '<base href="/datenblatt-editor/">' <<<"${editor_html}"; then
  echo "Editor response did not contain the expected public base path." >&2
  exit 1
fi

echo "Checking Datenblatt-Editor deep link ..."
deep_link_html="$(curl --fail --silent --show-error "${EDITOR_URL}/draft/smoke-test")"
if ! grep -q '<base href="/datenblatt-editor/">' <<<"${deep_link_html}"; then
  echo "Editor deep link did not contain the expected public base path." >&2
  exit 1
fi

echo "Checking Datenblatt-Editor HEAD ..."
curl --fail --silent --show-error --head "${EDITOR_URL}/" >/dev/null

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
  docker compose exec -T jenkins curl --fail --silent --show-error http://sodata:8080/actuator/health -o /dev/null

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

echo "Checking gateway routes and public admin denial ..."
python3 - "$SODATA_URL" <<'PYTHON'
import sys, urllib.request, urllib.error
base = sys.argv[1]
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args): return None
opener = urllib.request.build_opener(NoRedirect)
for path, expected, target in [
    ('/anlieferung', 302, '/jenkins/gretl-datenportal/'),
    ('/jenkins', 308, '/jenkins/'),
    ('/metadaten-editor', 308, '/datenblatt-editor/'),
    ('/metadaten-editor/draft/test?x=1', 308, '/datenblatt-editor/draft/test?x=1')]:
    try: response = opener.open(base + path)
    except urllib.error.HTTPError as error: response = error
    assert response.code == expected, (path, response.code)
    assert response.headers['Location'] == target, (path, response.headers['Location'])
for path in ['/admin', '/admin/catalog/status', '/admin/catalog/reload', '/actuator', '/actuator/health', '/apisix/admin/routes']:
    for method in ['GET', 'POST']:
        for headers in [{}, {'X-Reload-Token': 'invalid-smoke-token'}]:
            try: response = opener.open(urllib.request.Request(base + path, method=method, headers=headers))
            except urllib.error.HTTPError as error: response = error
            assert response.code == 403, (path, method, response.code)
PYTHON

docker compose exec -T jenkins bash -s -- "$SODATA_URL" <<'SH'
set -euo pipefail
if [[ -z "${ORG_GRADLE_PROJECT_portalReloadToken:-}" ]]; then
  echo "Skipping valid-token check: no reload token configured."
  exit 0
fi
for endpoint in status reload; do
  method=GET
  [[ "$endpoint" != reload ]] || method=POST
  code=$(printf 'X-Reload-Token: %s\n' "$ORG_GRADLE_PROJECT_portalReloadToken" |
    curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
      --header @- --request "$method" "$1/admin/catalog/$endpoint")
  [[ "$code" == 403 ]] || { echo "Public $endpoint with valid token returned $code" >&2; exit 1; }
done
SH

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

echo "Garage, S3 browser, Dokumentation, Datenblatt-Editor, Portal and Jenkins smoke tests passed."
