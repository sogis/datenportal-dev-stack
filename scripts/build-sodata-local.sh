#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_DIR}"

SODATA_BUILD_CONTEXT="$(docker compose -f compose.yaml -f compose.sodata-local.yaml config --format json | python3 -c '
import json, sys
print(json.load(sys.stdin)["services"]["sodata"]["build"]["context"])
')"

if [[ ! -f "${SODATA_BUILD_CONTEXT}/Dockerfile" ]]; then
  echo "Sodata-Repository nicht gefunden: ${SODATA_BUILD_CONTEXT}" >&2
  exit 1
fi

echo "Baue lokales Sodata-Image: datenportal-sodata:local"
echo "Sodata-Repository: ${SODATA_BUILD_CONTEXT}"

docker compose -f compose.yaml -f compose.sodata-local.yaml build sodata
