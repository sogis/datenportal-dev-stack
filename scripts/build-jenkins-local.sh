#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

JENKINS_DEV_DIR="${JENKINS_DEV_DIR:-${REPO_DIR}/../datenportal-jenkins-dev}"
PLUGIN_REPO="${PLUGIN_REPO:-${REPO_DIR}/../datenportal-jenkins-gretl-plugin}"
THEMEN_REPO_DIR="${THEMEN_REPO_DIR:-${REPO_DIR}/../datenportal-themenrepo}"
PLUGIN_SOURCE="${PLUGIN_SOURCE:-auto}"
PLUGIN_REPOSITORY_URL="${PLUGIN_REPOSITORY_URL:-https://jars.interlis.guru/snapshots}"
PLUGIN_VERSION="${PLUGIN_VERSION:-0.1.0-SNAPSHOT}"
IMAGE_NAME="${IMAGE_NAME:-datenportal-jenkins:local}"
IMAGE_VERSION="${IMAGE_VERSION:-local}"

if [[ ! -x "${JENKINS_DEV_DIR}/bin/build-image.sh" ]]; then
  echo "Jenkins-Dev-Buildscript nicht gefunden: ${JENKINS_DEV_DIR}/bin/build-image.sh" >&2
  exit 1
fi

if [[ ! -d "${THEMEN_REPO_DIR}" ]]; then
  echo "Themenrepo nicht gefunden: ${THEMEN_REPO_DIR}" >&2
  exit 1
fi

export THEMEN_REPO_DIR
export PLUGIN_REPO
export PLUGIN_SOURCE
export PLUGIN_REPOSITORY_URL
export PLUGIN_VERSION
export IMAGE_NAME
export IMAGE_VERSION

if [[ -n "${PLUGIN_HPI_SOURCE:-}" ]]; then
  export PLUGIN_HPI_SOURCE
fi

if [[ -n "${MAVEN_REPO_LOCAL:-}" ]]; then
  export MAVEN_REPO_LOCAL
fi

echo "Baue lokales Jenkins-Image: ${IMAGE_NAME}"
echo "Jenkins-Dev-Repository: ${JENKINS_DEV_DIR}"
echo "Themenrepo: ${THEMEN_REPO_DIR}"
echo "Plugin-Quelle: ${PLUGIN_SOURCE}"

exec "${JENKINS_DEV_DIR}/bin/build-image.sh"
