#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_DIR}"

compose_files=(-f compose.yaml)
local_editor=false
local_jenkins=false
registry_only=false

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --local-editor)
      local_editor=true
      compose_files+=(-f compose.editor-local.yaml)
      ;;
    --local-jenkins)
      local_jenkins=true
      ;;
    --registry-only)
      registry_only=true
      ;;
    --help|-h)
      echo "Usage: ./scripts/up.sh [--local-editor] [--local-jenkins] [--registry-only]"
      echo "  --local-editor   build the editor from ../datenportal-datenblatt-editor"
      echo "  --local-jenkins  build datenportal-jenkins from ../datenportal-jenkins-dev"
      echo "  --registry-only  never fall back to a local Jenkins build"
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      echo "Usage: ./scripts/up.sh [--local-editor] [--local-jenkins] [--registry-only]" >&2
      exit 2
      ;;
  esac
  shift
done

if [[ "$local_jenkins" == true && "$registry_only" == true ]]; then
  echo "--local-jenkins and --registry-only cannot be combined." >&2
  exit 2
fi

# Keep explicit shell overrides when .env is loaded below. This makes commands
# such as `PLUGIN_SOURCE=maven ./scripts/up.sh --local-jenkins` work while the
# generated Garage credentials still come from the local .env file.
environment_dataportal_jenkins_image="${DATENPORTAL_JENKINS_IMAGE-}"
environment_dataportal_jenkins_image_set="${DATENPORTAL_JENKINS_IMAGE+x}"
environment_jenkins_port="${JENKINS_PORT-}"
environment_jenkins_port_set="${JENKINS_PORT+x}"
environment_plugin_source="${PLUGIN_SOURCE-}"
environment_plugin_source_set="${PLUGIN_SOURCE+x}"
environment_plugin_version="${PLUGIN_VERSION-}"
environment_plugin_version_set="${PLUGIN_VERSION+x}"
environment_plugin_repository_url="${PLUGIN_REPOSITORY_URL-}"
environment_plugin_repository_url_set="${PLUGIN_REPOSITORY_URL+x}"

./scripts/init.sh
set -a
# shellcheck disable=SC1091
source .env
set +a

if [[ -n "$environment_dataportal_jenkins_image_set" ]]; then
  export DATENPORTAL_JENKINS_IMAGE="$environment_dataportal_jenkins_image"
fi
if [[ -n "$environment_jenkins_port_set" ]]; then
  export JENKINS_PORT="$environment_jenkins_port"
fi
if [[ -n "$environment_plugin_source_set" ]]; then
  export PLUGIN_SOURCE="$environment_plugin_source"
fi
if [[ -n "$environment_plugin_version_set" ]]; then
  export PLUGIN_VERSION="$environment_plugin_version"
fi
if [[ -n "$environment_plugin_repository_url_set" ]]; then
  export PLUGIN_REPOSITORY_URL="$environment_plugin_repository_url"
fi

if [[ "$local_editor" == true ]]; then
  docker compose "${compose_files[@]}" build datenblatt-editor
fi

jenkins_local=false
if [[ "$local_jenkins" == true ]]; then
  ./scripts/build-jenkins-local.sh
  jenkins_local=true
else
  jenkins_image="${DATENPORTAL_JENKINS_IMAGE:-sogis/datenportal-jenkins:0.1.0}"
  if docker image inspect "$jenkins_image" >/dev/null 2>&1; then
    echo "Using cached Jenkins image: $jenkins_image"
  else
    echo "Pulling Jenkins image: $jenkins_image"
    if pull_output="$(docker pull "$jenkins_image" 2>&1)"; then
      echo "$pull_output"
    else
      echo "$pull_output" >&2
      if [[ "$registry_only" == true ]]; then
        echo "Registry-only mode: Jenkins image could not be pulled." >&2
        exit 1
      fi

      shopt -s nocasematch
      registry_not_found=false
      if [[ "$pull_output" =~ manifest[[:space:]]+unknown|manifest[[:space:]]+for.*not[[:space:]]+found|name[[:space:]]+unknown|repository.*does[[:space:]]+not[[:space:]]+exist|no[[:space:]]+such[[:space:]]+manifest|failed[[:space:]]+to[[:space:]]+resolve[[:space:]]+reference.*:[[:space:]]+not[[:space:]]+found ]]; then
        registry_not_found=true
      fi
      shopt -u nocasematch

      if [[ "$registry_not_found" != true ]]; then
        echo "Jenkins image pull failed for a reason other than a missing registry tag." >&2
        echo "Use --local-jenkins explicitly if a local build is intended." >&2
        exit 1
      fi

      echo "Jenkins registry tag not found; falling back to the local Jenkins image."
      if docker image inspect datenportal-jenkins:local >/dev/null 2>&1; then
        echo "Using cached local Jenkins image: datenportal-jenkins:local"
      else
        echo "No cached local Jenkins image; building it now."
        ./scripts/build-jenkins-local.sh
      fi
      jenkins_local=true
    fi
  fi
fi

if [[ "$jenkins_local" == true ]]; then
  compose_files+=(-f compose.jenkins-local.yaml)
fi

docker compose "${compose_files[@]}" up -d --wait --wait-timeout 120 garage datenblatt-editor jenkins downloads
docker compose "${compose_files[@]}" run --rm garage-init

echo
echo "Garage-S3 is ready."
echo "S3 API:           http://localhost:${GARAGE_S3_PORT:-3900}"
echo "Public downloads: http://localhost:${GARAGE_PUBLIC_PORT:-8081}/ch.so.daten/"
echo "Datenblatt-Editor: http://localhost:${GARAGE_PUBLIC_PORT:-8081}/metadaten-editor/"
echo "Jenkins:          http://localhost:${JENKINS_PORT:-8080}/"
