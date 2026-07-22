#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# shellcheck disable=SC1091
source config/quality-tools.env

export UV_NO_PROGRESS=1

python scripts/check_github_action_pins.py
python scripts/check_migration_contracts.py
python scripts/check_python_lock_contract.py
python scripts/check_vercel_headers.py
python scripts/sync_release_manifest.py --check

# Confirm project metadata still matches the public-index lock, then synchronize it.
uv lock --check --default-index https://pypi.org/simple
uv sync --frozen --extra test
uv run --with "ruff==${RUFF_VERSION}" ruff check .
uv run --with "basedpyright==${BASEDPYRIGHT_VERSION}" basedpyright
uv run --with "pre-commit==${PRE_COMMIT_VERSION}" pre-commit run --all-files

mapfile -t javascript_files < <(
  git ls-files '*.js' '*.mjs' \
    | grep -Ev '^(src/vendor|artifacts|playwright-report)/' \
    || true
)
if ((${#javascript_files[@]} == 0)); then
  echo "No JavaScript files selected for Biome."
else
  pnpm dlx "@biomejs/biome@${BIOME_VERSION}" lint "${javascript_files[@]}"
fi

(
  cd supabase/functions/prediction-snapshot
  deno task check
  deno fmt --check
  deno lint
  deno task test
)

go install "github.com/rhysd/actionlint/cmd/actionlint@v${ACTIONLINT_VERSION}"
"$(go env GOPATH)/bin/actionlint"

go install "github.com/zricethezav/gitleaks/v8@v${GITLEAKS_VERSION}"
secret_scan_root="$(mktemp -d)"
cleanup() {
  rm -rf "$secret_scan_root"
}
trap cleanup EXIT
# Scan repository source only. Do not traverse synchronized virtual environments,
# package stores, browser downloads, reports, or other ignored build products.
git ls-files -z --cached --others --exclude-standard \
  | tar --null --files-from=- --create --file=- \
  | tar --extract --file=- --directory="$secret_scan_root"
"$(go env GOPATH)/bin/gitleaks" dir "$secret_scan_root" --redact --no-banner

uvx --from "pip-audit==${PIP_AUDIT_VERSION}" pip-audit \
  --requirement requirements.lock \
  --no-deps \
  --strict \
  --progress-spinner off

mapfile -t patch_sql < <(
  python - <<'PY'
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(newline="\n")
manifest = json.loads(Path("release-manifest.json").read_text(encoding="utf-8"))
for migration in manifest["repository_state"]["patch_added_migrations"]:
    print(Path("supabase/migrations", migration))
for path in sorted(Path("supabase/snippets").glob("*prediction_snapshot*.sql")):
    print(path)
PY
)
for path in "${patch_sql[@]}"; do
  uvx --from "sqlfluff==${SQLFLUFF_VERSION}" sqlfluff parse \
    --dialect postgres \
    "$path" >/dev/null
done
uvx --from "sqlfluff==${SQLFLUFF_VERSION}" sqlfluff lint \
  --dialect postgres \
  --rules LT12 \
  "${patch_sql[@]}"
