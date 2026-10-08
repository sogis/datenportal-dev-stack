#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${REPO_DIR}/.env"
ENV_EXAMPLE="${REPO_DIR}/.env.example"
CONFIG_TEMPLATE="${REPO_DIR}/services/garage/garage.toml.template"
CONFIG_FILE="${REPO_DIR}/services/garage/garage.toml"
caller_reload_token="${DATENPORTAL_PORTAL_RELOAD_TOKEN-}"
caller_reload_token_set="${DATENPORTAL_PORTAL_RELOAD_TOKEN+x}"

if ! command -v openssl >/dev/null 2>&1; then
  echo "openssl is required to generate local Garage secrets." >&2
  exit 1
fi

if [[ ! -f "${ENV_FILE}" ]]; then
  cp "${ENV_EXAMPLE}" "${ENV_FILE}"
  chmod 600 "${ENV_FILE}"
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

# Preserve an existing token (including a caller override). Only a missing local
# token is generated; no token value is printed or copied into tracked files.
if [[ -n "${caller_reload_token_set}" ]]; then
  DATENPORTAL_PORTAL_RELOAD_TOKEN="${caller_reload_token}"
elif [[ -z "${DATENPORTAL_PORTAL_RELOAD_TOKEN+x}" ]]; then
  # A newly created .env has not been loaded yet.
  set -a
  source "${ENV_FILE}"
  set +a
fi
if [[ -z "${DATENPORTAL_PORTAL_RELOAD_TOKEN:-}" ]]; then
  if [[ -n "${caller_reload_token_set}" ]]; then
    echo "DATENPORTAL_PORTAL_RELOAD_TOKEN is explicitly empty; complete startup requires a token." >&2
    exit 1
  fi
  # Remove only an empty assignment, never an existing non-empty secret.
  token_tmp="$(mktemp "${TMPDIR:-/tmp}/datenportal-env.XXXXXX")"
  trap 'rm -f "${token_tmp}"' EXIT
  sed '/^DATENPORTAL_PORTAL_RELOAD_TOKEN=[[:space:]]*$/d' "${ENV_FILE}" > "${token_tmp}"
  printf '\nDATENPORTAL_PORTAL_RELOAD_TOKEN=%s\n' "$(openssl rand -hex 32)" >> "${token_tmp}"
  chmod 600 "${token_tmp}"
  mv "${token_tmp}" "${ENV_FILE}"
  trap - EXIT
  echo "Generated local shared portal reload token."
fi

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
