#!/usr/bin/env bash
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "${1:-}" == --help || "${1:-}" == -h ]]; then
  echo 'Usage: scripts/build-docs-local.sh [--sources-root PATH]'
  echo 'Build local documentation with Thoth, then datenportal-dokumentation:local.'
  echo 'Environment: DOCS_REPO_DIR, THOTH_REPO_DIR, THOTH_JAR, PYTHON, JAVA_HOME'
  exit 0
fi
cd "$REPO_DIR"
DOCS_REPO_DIR="${DOCS_REPO_DIR:-${REPO_DIR}/../datenportal-dokumentation}"
[[ -f "$DOCS_REPO_DIR/Dockerfile" && -x "$DOCS_REPO_DIR/scripts/build-local.sh" ]] || {
  echo "Dokumentationsrepository mit Dockerfile und scripts/build-local.sh fehlt: $DOCS_REPO_DIR" >&2
  exit 1
}
DOCS_REPO_DIR="$(cd "$DOCS_REPO_DIR" && pwd)"
export DOCS_REPO_DIR
"$DOCS_REPO_DIR/scripts/build-local.sh" "$@"
echo 'Baue lokales Dokumentationsimage: datenportal-dokumentation:local'
docker compose -f compose.yaml -f compose.docs-local.yaml build dokumentation
