#!/usr/bin/env bash
set -euo pipefail

project_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
dist_root="$project_root/dist"

node "$project_root/scripts/generate-worker.mjs"
rm -rf "$dist_root"
mkdir -p "$dist_root/server"
cp "$project_root/worker/index.js" "$dist_root/server/index.js"
cp "$project_root/worker/deep-data.js" "$dist_root/server/deep-data.js"
cp "$project_root/worker/backend-store.js" "$dist_root/server/backend-store.js"

# The ChatGPT Sites manifest is intentionally absent from the GitHub export.
# Copy it only when this source is checked out inside a Sites workspace.
if [[ -f "$project_root/.openai/hosting.json" ]]; then
  mkdir -p "$dist_root/.openai"
  cp "$project_root/.openai/hosting.json" "$dist_root/.openai/hosting.json"
fi

echo "Built $dist_root"
