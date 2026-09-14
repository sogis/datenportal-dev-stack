#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_DIR}"

compose_files=(-f compose.yaml)
local_editor=false
local_jenkins=false
local_sodata=false
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
    --local-sodata)
      local_sodata=true
      ;;
    --registry-only)
      registry_only=true
      ;;
    --help|-h)
      echo "Usage: ./scripts/up.sh [--local-editor] [--local-jenkins] [--local-sodata] [--registry-only]"
      echo "  --local-editor   build the editor from ../datenportal-datenblatt-editor"
      echo "  --local-jenkins  build datenportal-jenkins from ../datenportal-jenkins-dev"
      echo "  --local-sodata   build datenportal-sodata from ../datenportal-sodata"
      echo "  --registry-only  never fall back to a local Jenkins or Sodata build"
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      echo "Usage: ./scripts/up.sh [--local-editor] [--local-jenkins] [--local-sodata] [--registry-only]" >&2
      exit 2
      ;;
  esac
  shift
done

if [[ "$registry_only" == true && ("$local_jenkins" == true || "$local_sodata" == true) ]]; then
  echo "--registry-only cannot be combined with --local-jenkins or --local-sodata." >&2
  exit 2
fi

# Keep explicit shell overrides when .env is loaded below. This makes commands
# such as `PLUGIN_SOURCE=maven ./scripts/up.sh --local-jenkins` work while the
# generated Garage credentials still come from the local .env file.
environment_dataportal_jenkins_image="${DATENPORTAL_JENKINS_IMAGE-}"
environment_dataportal_jenkins_image_set="${DATENPORTAL_JENKINS_IMAGE+x}"
environment_dataportal_sodata_image="${DATENPORTAL_SODATA_IMAGE-}"
environment_dataportal_sodata_image_set="${DATENPORTAL_SODATA_IMAGE+x}"
environment_jenkins_port="${JENKINS_PORT-}"
environment_jenkins_port_set="${JENKINS_PORT+x}"
environment_sodata_port="${SODATA_PORT-}"
environment_sodata_port_set="${SODATA_PORT+x}"
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
if [[ -n "$environment_dataportal_sodata_image_set" ]]; then
  export DATENPORTAL_SODATA_IMAGE="$environment_dataportal_sodata_image"
fi
if [[ -n "$environment_jenkins_port_set" ]]; then
  export JENKINS_PORT="$environment_jenkins_port"
fi
if [[ -n "$environment_sodata_port_set" ]]; then
  export SODATA_PORT="$environment_sodata_port"
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

# Versucht ein Registry-Image zu verwenden. Liefert 1 zurueck, wenn der
# Registry-Tag eindeutig fehlt und ein lokaler Build-Fallback erlaubt ist.
resolve_registry_image() {
  local image="$1"
  local component="$2"
  local pull_output

  if docker image inspect "$image" >/dev/null 2>&1; then
    echo "Using cached ${component} image: $image"
    return 0
  fi

  echo "Pulling ${component} image: $image"
  if pull_output="$(docker pull "$image" 2>&1)"; then
    echo "$pull_output"
    return 0
  fi

  echo "$pull_output" >&2
  if [[ "$registry_only" == true ]]; then
    echo "Registry-only mode: ${component} image could not be pulled." >&2
    exit 1
  fi

  shopt -s nocasematch
  local registry_not_found=false
  if [[ "$pull_output" =~ manifest[[:space:]]+unknown|manifest[[:space:]]+for.*not[[:space:]]+found|name[[:space:]]+unknown|repository.*does[[:space:]]+not[[:space:]]+exist|no[[:space:]]+such[[:space:]]+manifest|failed[[:space:]]+to[[:space:]]+resolve[[:space:]]+reference.*:[[:space:]]+not[[:space:]]+found ]]; then
    registry_not_found=true
  fi
  shopt -u nocasematch

  if [[ "$registry_not_found" != true ]]; then
    echo "${component} image pull failed for a reason other than a missing registry tag." >&2
    echo "Use the local build option explicitly if a local build is intended." >&2
    exit 1
  fi

  return 1
}

jenkins_local=false
if [[ "$local_jenkins" == true ]]; then
  ./scripts/build-jenkins-local.sh
  jenkins_local=true
elif ! resolve_registry_image "${DATENPORTAL_JENKINS_IMAGE:-sogis/datenportal-jenkins:0.1.0}" "Jenkins"; then
  echo "Jenkins registry tag not found; falling back to the local Jenkins image."
  if docker image inspect datenportal-jenkins:local >/dev/null 2>&1; then
    echo "Using cached local Jenkins image: datenportal-jenkins:local"
  else
    echo "No cached local Jenkins image; building it now."
    ./scripts/build-jenkins-local.sh
  fi
  jenkins_local=true
fi

if [[ "$jenkins_local" == true ]]; then
  compose_files+=(-f compose.jenkins-local.yaml)
fi

sodata_local=false
if [[ "$local_sodata" == true ]]; then
  ./scripts/build-sodata-local.sh
  sodata_local=true
elif ! resolve_registry_image "${DATENPORTAL_SODATA_IMAGE:-sogis/datenportal-sodata:0.1.0}" "Sodata"; then
  echo "Sodata registry tag not found; falling back to the local Sodata image."
  if docker image inspect datenportal-sodata:local >/dev/null 2>&1; then
    echo "Using cached local Sodata image: datenportal-sodata:local"
  else
    echo "No cached local Sodata image; building it now."
    ./scripts/build-sodata-local.sh
  fi
  sodata_local=true
fi

if [[ "$sodata_local" == true ]]; then
  compose_files+=(-f compose.sodata-local.yaml)
fi

sync_local_jenkins_plugin() {
  echo "Synchronisiere lokales GRETL-Datenportal-Plugin ins Jenkins-Volume ..."
  docker compose "${compose_files[@]}" run \
    --rm \
    --no-deps \
    --no-TTY \
    --user root \
    --entrypoint /bin/sh \
    jenkins \
    -c '
      set -eu
      plugin_dir=/var/jenkins_home/plugins
      image_plugin=/usr/share/jenkins/ref/plugins/jenkins-gretl-datenportal-plugin.jpi
      installed_plugin="$plugin_dir/jenkins-gretl-datenportal-plugin.jpi"

      if [ ! -f "$image_plugin" ]; then
        echo "Plugin aus dem Jenkins-Image nicht gefunden: $image_plugin" >&2
        exit 1
      fi

      mkdir -p "$plugin_dir"
      cp "$image_plugin" "$installed_plugin"
      chown jenkins:jenkins "$installed_plugin"
      rm -f "$plugin_dir/jenkins-gretl-datenportal-plugin.hpi"
      rm -rf "$plugin_dir/jenkins-gretl-datenportal-plugin"
    '
}

ensure_public_browser_key() {
  local key_id="${GARAGE_BROWSER_ACCESS_KEY}"

  echo "Konfiguriere dedizierten Read-only-Schlüssel für den öffentlichen S3-Browser ..."
  if ! docker compose "${compose_files[@]}" exec -T garage \
    /garage key info "${key_id}" >/dev/null 2>&1; then
    docker compose "${compose_files[@]}" exec -T garage \
      /garage key import \
      "${key_id}" \
      "${GARAGE_BROWSER_SECRET_KEY}" \
      -n "datenportal public browser" \
      --yes >/dev/null
  fi

  docker compose "${compose_files[@]}" exec -T garage \
    /garage key deny "${key_id}" --create-bucket >/dev/null
  docker compose "${compose_files[@]}" exec -T garage \
    /garage bucket deny --write --owner ch.so.daten --key "${key_id}" >/dev/null
  docker compose "${compose_files[@]}" exec -T garage \
    /garage bucket allow --read ch.so.daten --key "${key_id}" >/dev/null

  if ! docker compose "${compose_files[@]}" --profile tools run \
    --rm \
    --no-deps \
    -e AWS_ACCESS_KEY_ID="${GARAGE_BROWSER_ACCESS_KEY}" \
    -e AWS_SECRET_ACCESS_KEY="${GARAGE_BROWSER_SECRET_KEY}" \
    aws s3api head-bucket --bucket ch.so.daten >/dev/null; then
    echo "Der konfigurierte Browser-Schlüssel kann ch.so.daten nicht lesen." >&2
    echo "Prüfe die GARAGE_BROWSER_*-Werte in .env oder erzeuge die lokale Testinstanz neu." >&2
    exit 1
  fi
}

docker compose "${compose_files[@]}" up -d --wait --wait-timeout 120 garage
docker compose "${compose_files[@]}" run --rm garage-init
ensure_public_browser_key

if [[ "$jenkins_local" == true ]]; then
  docker compose "${compose_files[@]}" up -d --wait --wait-timeout 120 datenblatt-editor s3-browser downloads
  sync_local_jenkins_plugin
  docker compose "${compose_files[@]}" up -d --force-recreate --wait --wait-timeout 120 jenkins
else
  docker compose "${compose_files[@]}" up -d --wait --wait-timeout 120 datenblatt-editor s3-browser jenkins downloads
fi

# Das Portal wird bewusst ohne Health-Wait gestartet: Vor der ersten
# Veroeffentlichung fehlt current.json, die Anwendung startet dann nicht und der
# Container wiederholt den Start gemaess Restart-Policy, bis die Datei existiert.
docker compose "${compose_files[@]}" up -d sodata

echo
echo "Garage-S3 is ready."
echo "S3 API:           http://localhost:${GARAGE_S3_PORT:-3900}"
echo "Public S3 browser: http://localhost:${GARAGE_PUBLIC_PORT:-8081}/ch.so.daten/"
echo "Datenblatt-Editor: http://localhost:${GARAGE_PUBLIC_PORT:-8081}/metadaten-editor/"
echo "Jenkins:          http://localhost:${JENKINS_PORT:-8080}/gretl-datenportal/"
echo "Portal (sodata):  http://localhost:${SODATA_PORT:-8082}/"
if ! curl --fail --silent --show-error --max-time 5 \
  "http://localhost:${GARAGE_PUBLIC_PORT:-8081}/ch.so.daten/current.json" >/dev/null 2>&1; then
  echo "Hinweis: current.json fehlt noch. Das Portal startet neu, bis die erste Publikation vorliegt;"
  echo "danach ggf. 'docker compose restart sodata' ausfuehren."
fi
