#!/usr/bin/env bash
# Regenerate rudder_sdk/ from a RUNNING control plane's OpenAPI schema.
#
#   docker compose -f docker-compose.dev.yml up -d      # control plane on :8000
#   ./sdk-python/regenerate.sh                          # or: RUDDER_URL=... ./regenerate.sh
#
# Only rudder_sdk/ is replaced. pyproject.toml, README.md, openapi-config.yml
# and this script are hand-maintained and are NOT generator output — the
# generator emits a Poetry pyproject that we do not use.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUDDER_URL="${RUDDER_URL:-http://localhost:8000}"

if ! command -v openapi-python-client >/dev/null 2>&1; then
  echo "openapi-python-client is not on PATH. Install it first:" >&2
  echo "  pip install 'openapi-python-client==0.29.0'" >&2
  exit 1
fi

if ! curl -fsS "${RUDDER_URL}/openapi.json" -o /dev/null; then
  echo "Cannot reach ${RUDDER_URL}/openapi.json — is the control plane running?" >&2
  exit 1
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

openapi-python-client generate \
  --url "${RUDDER_URL}/openapi.json" \
  --config "${HERE}/openapi-config.yml" \
  --output-path "${TMP}/rudder-sdk" \
  --overwrite

rm -rf "${HERE}/rudder_sdk"
cp -R "${TMP}/rudder-sdk/rudder_sdk" "${HERE}/rudder_sdk"

echo "Regenerated ${HERE}/rudder_sdk from ${RUDDER_URL}"
echo "Reinstall if needed:  pip install -e ${HERE}"
