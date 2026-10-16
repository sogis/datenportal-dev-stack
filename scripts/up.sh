#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_DIR}"

compose_files=(-f compose.yaml)
local_sodata=false
registry_only=false

usage() {
  echo "Usage: ./scripts/up.sh [--registry-only | --local-sodata]"
  echo "  Default          start Sodata and APISIX with versioned registry images"
  echo "  --registry-only  explicit alias for the default (no sibling checkouts)"
  echo "  --local-sodata   build Sodata from ../datenportal-sodata (SODATA_REPO_DIR overrides)"
}

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --local-sodata) local_sodata=true ;;
    --registry-only) registry_only=true ;;
    --local-editor|--local-jenkins|--local-docs|--infrastructure-only)
      echo "$1 ist im Branch s3-aws deaktiviert; aktiv sind nur Sodata und APISIX." >&2
      exit 2
      ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

if [[ "$registry_only" == true && "$local_sodata" == true ]]; then
  echo "--registry-only cannot be combined with --local-sodata." >&2
  exit 2
fi
if [[ "$local_sodata" == true ]]; then
  compose_files+=(-f compose.sodata-local.yaml)
fi

# Compose reads optional .env itself and preserves shell precedence. No init,
# credentials, seed or publication is required for public AWS HTTPS sources.
docker compose "${compose_files[@]}" config --quiet
portal_url="$(docker compose "${compose_files[@]}" config --format json | python3 -c '
import json, sys
try:
    port = json.load(sys.stdin)["services"]["downloads"]["ports"][0]["published"]
    print("http://localhost:" + str(port) + "/")
except (ValueError, KeyError, IndexError, TypeError):
    sys.exit("Could not resolve APISIX host port from Compose configuration.")
')"

if [[ "$local_sodata" == true ]]; then
  ./scripts/build-sodata-local.sh
  docker compose "${compose_files[@]}" pull --policy missing downloads
else
  docker compose "${compose_files[@]}" pull --policy missing sodata downloads
fi

# Removes only obsolete containers in this Compose project; named volumes stay.
docker compose "${compose_files[@]}" up -d --remove-orphans --wait --wait-timeout 120
docker compose "${compose_files[@]}" ps
echo "Portal (sodata über APISIX): ${portal_url}"
