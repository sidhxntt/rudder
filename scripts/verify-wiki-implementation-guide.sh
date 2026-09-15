#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
guide="$repo_root/docs/implementation-guide.md"

test -s "$guide"

for required in \
  'services/deploy.py' \
  'GitHubAppClient' \
  'DockerOps' \
  'KubernetesRuntime' \
  'github_oauth.py' \
  'operations.py' \
  'web/lib/api.ts' \
  'cli/node/src/client.ts' \
  'services/assistant.py'; do
  grep -Fq "$required" "$guide" || grep -Fq "$required" "$repo_root/scripts/render-github-wiki.mjs"
done

grep -Fq 'Engineering-Implementation-Guide.md' "$repo_root/scripts/render-github-wiki.mjs"
grep -Fq 'Engineering-Implementation-Guide' "$repo_root/docs/_Sidebar.md"
grep -Fq 'implementation-guide.md' "$repo_root/docs/index.md"

echo 'Rudder Wiki implementation guide verification passed.'
