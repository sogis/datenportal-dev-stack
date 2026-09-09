#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${REPO_DIR}/.env"
ENV_EXAMPLE="${REPO_DIR}/.env.example"
CONFIG_TEMPLATE="${REPO_DIR}/services/garage/garage.toml.template"
CONFIG_FILE="${REPO_DIR}/services/garage/garage.toml"

if ! command -v openssl >/dev/null 2>&1; then
  echo "openssl is required to generate local Garage secrets." >&2
  exit 1
fi

if [[ ! -f "${ENV_FILE}" ]]; then
  cp "${ENV_EXAMPLE}" "${ENV_FILE}"
  {
    printf '\n# Generated locally by scripts/init.sh. Do not commit this file.\n'
    printf 'GARAGE_DEFAULT_ACCESS_KEY=GK%s\n' "$(openssl rand -hex 16)"
    printf 'GARAGE_DEFAULT_SECRET_KEY=%s\n' "$(openssl rand -hex 32)"
    printf 'GARAGE_BROWSER_ACCESS_KEY=GK%s\n' "$(openssl rand -hex 16)"
    printf 'GARAGE_BROWSER_SECRET_KEY=%s\n' "$(openssl rand -hex 32)"
  } >> "${ENV_FILE}"
  chmod 600 "${ENV_FILE}"
  echo "Created local .env with generated Garage access credentials."
else
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
  if [[ -z "${GARAGE_DEFAULT_ACCESS_KEY:-}" || -z "${GARAGE_DEFAULT_SECRET_KEY:-}" ]]; then
    echo "${ENV_FILE} exists but does not contain Garage credentials." >&2
    echo "Set both GARAGE_DEFAULT_ACCESS_KEY and GARAGE_DEFAULT_SECRET_KEY, or remove the local .env and rerun this script." >&2
    exit 1
  fi

  if [[ -z "${GARAGE_BROWSER_ACCESS_KEY:-}" && -z "${GARAGE_BROWSER_SECRET_KEY:-}" ]]; then
    {
      printf '\n# Generated locally by scripts/init.sh for the anonymous read-only browser.\n'
      printf 'GARAGE_BROWSER_ACCESS_KEY=GK%s\n' "$(openssl rand -hex 16)"
      printf 'GARAGE_BROWSER_SECRET_KEY=%s\n' "$(openssl rand -hex 32)"
    } >> "${ENV_FILE}"
    echo "Added generated Garage browser credentials to the existing local .env."
  elif [[ -z "${GARAGE_BROWSER_ACCESS_KEY:-}" || -z "${GARAGE_BROWSER_SECRET_KEY:-}" ]]; then
    echo "${ENV_FILE} contains only one of the two Garage browser credentials." >&2
    echo "Set both GARAGE_BROWSER_ACCESS_KEY and GARAGE_BROWSER_SECRET_KEY, or remove both entries and rerun this script." >&2
    exit 1
  fi
  echo "Using existing local .env."
fi
chmod 600 "${ENV_FILE}"

if [[ ! -f "${CONFIG_FILE}" ]]; then
  config_tmp="$(mktemp "${TMPDIR:-/tmp}/datenportal-garage-config.XXXXXX")"
  cleanup() {
    rm -f "${config_tmp}"
  }
  trap cleanup EXIT

  sed \
    -e "s/__RPC_SECRET__/$(openssl rand -hex 32)/" \
    -e "s/__ADMIN_TOKEN__/$(openssl rand -hex 32)/" \
    -e "s/__METRICS_TOKEN__/$(openssl rand -hex 32)/" \
    "${CONFIG_TEMPLATE}" > "${config_tmp}"
  chmod 600 "${config_tmp}"
  mv "${config_tmp}" "${CONFIG_FILE}"
  trap - EXIT
  echo "Created local Garage configuration with generated secrets."
else
  echo "Using existing local Garage configuration."
fi
chmod 600 "${CONFIG_FILE}"
