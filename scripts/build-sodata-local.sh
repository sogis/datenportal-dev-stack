#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_DIR}"

SODATA_REPO_DIR="${SODATA_REPO_DIR:-${REPO_DIR}/../datenportal-sodata}"

if [[ ! -f "${SODATA_REPO_DIR}/Dockerfile" ]]; then
  echo "Sodata-Repository nicht gefunden: ${SODATA_REPO_DIR}" >&2
  exit 1
fi

export SODATA_REPO_DIR

echo "Baue lokales Sodata-Image: datenportal-sodata:local"
echo "Sodata-Repository: ${SODATA_REPO_DIR}"

docker compose -f compose.yaml -f compose.sodata-local.yaml build sodata
