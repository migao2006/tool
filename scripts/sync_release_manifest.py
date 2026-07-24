from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "release-manifest.json"
MODEL_CARD_JSON_PATH = ROOT / "model_card.json"
MODEL_CARD_MARKDOWN_PATH = ROOT / "model_card.md"
CURRENT_STATUS_PATH = ROOT / "docs/current-status.md"
RELEASE_STATE_PATH = ROOT / "docs/release-state.md"
QUALITY_TOOL_VERSIONS_PATH = ROOT / "config/quality-tools.env"
PROJECT_TESTS_WORKFLOW_PATH = ROOT / ".github/workflows/project-tests.yml"
MANIFEST_DIGEST_PATH = ROOT / "release-manifest.sha256"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")

MODEL_HEADER_START = "<!-- release-manifest:model-header:start -->"
MODEL_HEADER_END = "<!-- release-manifest:model-header:end -->"
MODEL_SNAPSHOT_START = "<!-- release-manifest:model-snapshot:start -->"
MODEL_SNAPSHOT_END = "<!-- release-manifest:model-snapshot:end -->"
STATUS_HEADER_START = "<!-- release-manifest:status-header:start -->"
STATUS_HEADER_END = "<!-- release-manifest:status-header:end -->"
STATUS_SNAPSHOT_START = "<!-- release-manifest:status-snapshot:start -->"
STATUS_SNAPSHOT_END = "<!-- release-manifest:status-snapshot:end -->"


class ManifestError(ValueError):
    pass


def load_manifest() -> dict[str, Any]:
    payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    validate_manifest(payload)
    return payload


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ManifestError(message)


def load_shell_assignments(path: Path) -> dict[str, str]:
    assignments: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        require("=" in line, f"{path.name}:{line_number} is not a KEY=VALUE assignment")
        key, value = line.split("=", 1)
        require(
            re.fullmatch(r"[A-Z][A-Z0-9_]*", key) is not None and bool(value),
            f"{path.name}:{line_number} has an invalid assignment",
        )
        require(key not in assignments, f"{path.name} contains duplicate key {key}")
        assignments[key] = value
    return assignments


def validate_manifest(manifest: dict[str, Any]) -> None:
    require(
        manifest.get("schema_version") == "alpha-lens-release-manifest.v1",
        "unsupported release manifest schema",
    )
    model = manifest.get("model_card")
    require(isinstance(model, dict), "model_card must be an object")
    assert isinstance(model, dict)
    require(model.get("status") == "RESEARCH_ONLY", "status must stay RESEARCH_ONLY")
    require(model.get("production_horizon") == 5, "only horizon=5 is released")
    require(model.get("formal_pass") is False, "formal_pass must remain false")

    snapshot = model.get("published_research_snapshot")
    require(isinstance(snapshot, dict), "published_research_snapshot is required")
    assert isinstance(snapshot, dict)
    require(snapshot.get("status") == "RESEARCH_ONLY", "snapshot status must be RESEARCH_ONLY")
    require(
        snapshot.get("evidence_scope") == "LATEST_FULLY_ARTIFACT_AND_PROVENANCE_BACKED_SNAPSHOT",
        "snapshot evidence scope must not imply it is the latest Production run",
    )
    prediction_count = snapshot.get("prediction_count")
    require(
        isinstance(prediction_count, int) and prediction_count > 0, "prediction_count is invalid"
    )
    assert isinstance(prediction_count, int)
    decision_total = sum(
        int(snapshot.get(name, -prediction_count))
        for name in (
            "candidate_count",
            "watch_count",
            "no_trade_count",
            "policy_input_missing_count",
            "policy_validation_failed_count",
            "policy_hard_fail_count",
        )
    )
    require(
        decision_total == prediction_count,
        "snapshot action and policy status counts do not add up",
    )
    require(
        snapshot.get("decision_policy_semantics")
        == "LEGACY_NO_TRADE_RECLASSIFIED_MISSING_REQUIRED_DATA",
        "legacy snapshot semantics must be explicitly reclassified",
    )
    require(
        snapshot.get("legacy_persisted_no_trade_count") == prediction_count
        and snapshot.get("no_trade_count") == 0
        and snapshot.get("policy_input_missing_count") == prediction_count,
        "legacy NO_TRADE evidence must remain distinct from its corrected status",
    )
    gate_count = snapshot.get("decision_gate_count")
    gates_per_prediction = snapshot.get("decision_gates_per_prediction")
    require(isinstance(gate_count, int), "decision_gate_count must be an integer")
    require(
        isinstance(gates_per_prediction, int),
        "decision_gates_per_prediction must be an integer",
    )
    assert isinstance(gate_count, int)
    assert isinstance(gates_per_prediction, int)
    require(
        gate_count == prediction_count * gates_per_prediction,
        "decision gate count does not match the per-prediction contract",
    )
    for name in (
        "feature_artifact_sha256",
        "model_bundle_sha256",
        "snapshot_sha256",
        "snapshot_artifact_sha256",
        "github_artifact_digest",
    ):
        require(
            isinstance(snapshot.get(name), str)
            and SHA256_PATTERN.fullmatch(snapshot[name]) is not None,
            f"{name} must be a lowercase SHA-256 digest",
        )
    workflow_run_id = snapshot.get("workflow_run_id")
    require(
        str(workflow_run_id) in str(snapshot.get("workflow_url")),
        "workflow URL and workflow run ID disagree",
    )
    commit = snapshot.get("git_commit")
    require(
        commit is None
        or (isinstance(commit, str) and COMMIT_PATTERN.fullmatch(commit) is not None),
        "git_commit must be null or a full 40-character commit",
    )
    if commit is None:
        require(
            snapshot.get("git_commit_evidence_status") == "NOT_RECORDED_IN_AVAILABLE_EVIDENCE",
            "an unknown publication commit must be explicitly disclosed",
        )

    repository_state = manifest.get("repository_state")
    require(isinstance(repository_state, dict), "repository_state is required")
    assert isinstance(repository_state, dict)
    migration_count = len(list((ROOT / "supabase/migrations").glob("*.sql")))
    require(
        repository_state.get("migration_file_count") == migration_count,
        "repository migration count is stale",
    )
    migration_names = {path.name for path in (ROOT / "supabase/migrations").glob("*.sql")}
    for field in (
        "patch_added_migrations",
        "patch_requires_staging_validation",
        "migrations_after_recorded_remote_latest",
    ):
        entries = repository_state.get(field)
        require(isinstance(entries, list), f"{field} must be an array")
        assert isinstance(entries, list)
        require(len(entries) == len(set(entries)), f"{field} contains duplicates")
        for migration in entries:
            require(
                isinstance(migration, str) and migration in migration_names,
                f"{field} references a missing migration: {migration}",
            )
    patch_added = set(repository_state["patch_added_migrations"])
    requires_validation = set(repository_state["patch_requires_staging_validation"])
    after_remote = set(repository_state["migrations_after_recorded_remote_latest"])
    require(
        patch_added <= requires_validation <= after_remote,
        "patch migration evidence sets are inconsistent",
    )
    histories = repository_state.get("environment_migration_history")
    require(isinstance(histories, dict), "environment migration history is required")
    assert isinstance(histories, dict)
    for environment in ("staging", "production"):
        history = histories.get(environment)
        require(isinstance(history, dict), f"{environment} history is required")
        assert isinstance(history, dict)
        latest = history.get("recorded_latest_migration")
        require(
            isinstance(latest, str) and latest in migration_names,
            f"{environment} latest migration is missing",
        )
        assert isinstance(latest, str)
        later_names = sorted(name for name in migration_names if name > latest)
        require(
            later_names == repository_state["migrations_after_recorded_remote_latest"],
            f"{environment} migration evidence gap is stale",
        )

    hardening = manifest.get("platform_hardening")
    require(isinstance(hardening, dict), "platform_hardening is required")
    assert isinstance(hardening, dict)

    snapshot_read = hardening.get("prediction_snapshot")
    require(isinstance(snapshot_read, dict), "prediction_snapshot hardening is required")
    assert isinstance(snapshot_read, dict)
    require(snapshot_read.get("default_mode") == "rpc", "snapshot default mode must be rpc")
    require(
        snapshot_read.get("emergency_rollback_mode") == "legacy",
        "snapshot rollback mode must be legacy",
    )
    require(
        snapshot_read.get("fallback_condition") == "EXPLICIT_LEGACY_MODE_ONLY",
        "snapshot reads must not silently fall back",
    )
    require(
        snapshot_read.get("expected_primary_postgrest_requests") == 1,
        "snapshot primary path must use one PostgREST request",
    )
    require(
        snapshot_read.get("migration") in patch_added,
        "snapshot RPC migration must be part of this patch",
    )
    require(
        snapshot_read.get("remote_status") == "REPOSITORY_ONLY_NOT_REMOTELY_VERIFIED",
        "snapshot RPC remote status must preserve the evidence boundary",
    )
    require(
        snapshot_read.get("deployment_guard") == "RPC_MIGRATION_VERIFIED_ATTESTATION_REQUIRED",
        "snapshot RPC deployment must require migration verification attestation",
    )
    require(
        snapshot_read.get("decision_policy_rollout_order")
        == [
            "STATUS_AWARE_FRONTEND_AND_EDGE",
            "DECISION_POLICY_STATUS_MIGRATION",
            "STATUS_AWARE_PUBLISHER",
        ],
        "Decision Policy rollout order is unsafe or stale",
    )
    require(
        snapshot_read.get("decision_policy_rollback_constraint")
        == "DO_NOT_ROLL_BACK_EDGE_BEFORE_DATABASE_CONTRACT",
        "Decision Policy rollback constraint is unsafe or stale",
    )
    require(
        snapshot_read.get("primary_read_path")
        == "market_data.get_prediction_snapshot_rows_v2(integer,text,timestamptz)",
        "snapshot primary path must use the calendar-aware v2 RPC",
    )
    require(
        snapshot_read.get("base_migration") == "20260720190000_prediction_snapshot_read_rpc.sql",
        "snapshot base migration is invalid",
    )
    require(
        snapshot_read.get("base_migration") in patch_added,
        "snapshot base migration must remain in the patch evidence set",
    )
    freshness = snapshot_read.get("freshness_policy")
    require(isinstance(freshness, dict), "snapshot freshness policy is required")
    assert isinstance(freshness, dict)
    expected_freshness = {
        "preferred_method": "TRADING_CALENDAR",
        "fallback_method": "WALL_CLOCK_FALLBACK",
        "required_calendar_verification_status": "VERIFIED",
        "required_market_basis": "SOURCE_ASSERTED",
        "required_usage_scope": "POINT_IN_TIME_CALENDAR",
        "required_system_status": "PASS",
        "default_ready_hour_taipei": 17,
        "default_lookback_days": 45,
        "maximum_lookback_days": 62,
        "rpc_calendar_window_days": 63,
        "fallback_stale_hours": 72,
        "calendar_gap_behavior": "EXPLICIT_CONSERVATIVE_FALLBACK",
    }
    require(
        freshness == expected_freshness,
        "snapshot freshness policy differs from the released contract",
    )

    p2_refactoring = hardening.get("p2_refactoring")
    require(isinstance(p2_refactoring, dict), "P2 refactoring evidence is required")
    assert isinstance(p2_refactoring, dict)
    for field in ("monthly_benchmark_orchestrator", "venue_feature_cli_orchestrator"):
        relative_path = p2_refactoring.get(field)
        require(isinstance(relative_path, str), f"{field} path is invalid")
        assert isinstance(relative_path, str)
        require((ROOT / relative_path).is_file(), f"{field} file is missing")
    require(
        p2_refactoring.get("public_venue_adapters_preserved") is True,
        "venue adapter compatibility must be preserved",
    )
    require(
        p2_refactoring.get("remote_status") == "REPOSITORY_ONLY_NOT_REMOTELY_VERIFIED",
        "P2 refactoring remote status must preserve the evidence boundary",
    )
    for field in (
        "historical_backfill_run_lines",
        "daily_inference_run_lines",
        "research_dataset_from_frame_lines",
    ):
        value = p2_refactoring.get(field)
        require(isinstance(value, int) and 1 <= value <= 80, f"{field} is invalid")

    auth_recovery = hardening.get("auth_recovery")
    require(isinstance(auth_recovery, dict), "auth recovery evidence is required")
    assert isinstance(auth_recovery, dict)
    expected_auth = {
        "provider": "SUPABASE_AUTH",
        "flow_type": "pkce",
        "recovery_event": "PASSWORD_RECOVERY",
        "redirect_policy": "SAME_ORIGIN_AND_SUPABASE_ALLOWLIST_REQUIRED",
        "account_enumeration_response": "GENERIC",
        "sensitive_callback_parameters_removed": True,
        "redirect_allowlist_status": "NOT_REVERIFIED_BY_THIS_PATCH",
        "production_smtp_status": "NOT_REVERIFIED_BY_THIS_PATCH",
    }
    require(auth_recovery == expected_auth, "auth recovery contract is stale")
    for relative_path in (
        "src/features/auth/auth-callback.js",
        "src/features/auth/auth-service.js",
        "src/auth/auth-controller.js",
    ):
        require((ROOT / relative_path).is_file(), f"auth recovery file is missing: {relative_path}")

    continuous_integration = hardening.get("continuous_integration")
    require(isinstance(continuous_integration, dict), "CI hardening is required")
    assert isinstance(continuous_integration, dict)
    quality_job_id = continuous_integration.get("quality_job_id")
    required_gate_job_id = continuous_integration.get("required_gate_job_id")
    require(quality_job_id == "quality-security", "quality-security job is required")
    require(required_gate_job_id == "test-gate", "test-gate must remain the aggregate gate")
    require(
        continuous_integration.get("github_actions_pinned_to_full_sha") is True,
        "GitHub Actions must be pinned to full SHAs",
    )
    require(
        continuous_integration.get("branch_protection_status") == "NOT_REVERIFIED_BY_THIS_PATCH",
        "remote branch-protection status must not be inferred",
    )
    action_pin_policy = continuous_integration.get("action_pin_policy")
    tool_version_file = continuous_integration.get("tool_version_file")
    require(
        action_pin_policy == "config/github-actions-pins.json", "action pin policy path is invalid"
    )
    require(tool_version_file == "config/quality-tools.env", "tool version file path is invalid")
    assert isinstance(action_pin_policy, str)
    assert isinstance(tool_version_file, str)
    require((ROOT / action_pin_policy).is_file(), "action pin policy is missing")
    require((ROOT / tool_version_file).is_file(), "tool version file is missing")

    version_assignments = load_shell_assignments(QUALITY_TOOL_VERSIONS_PATH)
    expected_tools = {
        "ruff": version_assignments.get("RUFF_VERSION"),
        "basedpyright": version_assignments.get("BASEDPYRIGHT_VERSION"),
        "pre-commit": version_assignments.get("PRE_COMMIT_VERSION"),
        "pip-audit": version_assignments.get("PIP_AUDIT_VERSION"),
        "sqlfluff": version_assignments.get("SQLFLUFF_VERSION"),
        "biome": version_assignments.get("BIOME_VERSION"),
        "actionlint": version_assignments.get("ACTIONLINT_VERSION"),
        "gitleaks": version_assignments.get("GITLEAKS_VERSION"),
        "go": version_assignments.get("GO_VERSION"),
        "deno": version_assignments.get("DENO_VERSION"),
    }
    require(all(expected_tools.values()), "quality tool version file is incomplete")
    require(
        continuous_integration.get("tools") == expected_tools,
        "manifest CI tool versions differ from config/quality-tools.env",
    )
    deno_version = expected_tools["deno"]
    assert isinstance(deno_version, str)
    deploy_workflow_text = (
        ROOT / ".github/workflows/deploy-prediction-edge-function.yml"
    ).read_text(encoding="utf-8")
    require(
        f"deno-version: v{deno_version}" in deploy_workflow_text,
        "prediction Edge workflow must use the pinned Deno version",
    )
    workflow_text = PROJECT_TESTS_WORKFLOW_PATH.read_text(encoding="utf-8")
    require(f"  {quality_job_id}:" in workflow_text, "quality job is missing from project-tests")
    require(f"  {required_gate_job_id}:" in workflow_text, "aggregate test gate is missing")
    gate_section = workflow_text.split(f"  {required_gate_job_id}:", 1)[1]
    require(
        f"      - {quality_job_id}" in gate_section,
        "aggregate test gate does not depend on quality-security",
    )

    vercel = hardening.get("vercel")
    require(isinstance(vercel, dict), "Vercel hardening is required")
    assert isinstance(vercel, dict)
    require(vercel.get("config_file") == "vercel.json", "Vercel config path is invalid")
    require((ROOT / vercel["config_file"]).is_file(), "Vercel config file is missing")
    require(vercel.get("csp_enforced") is True, "Vercel CSP must be enforced")
    require(vercel.get("inline_script_allowed") is False, "inline scripts must remain blocked")
    require(vercel.get("inline_style_allowed") is False, "inline styles must remain blocked")
    require(
        vercel.get("remote_response_headers_verified") is False,
        "remote Vercel headers were not verified by this patch",
    )

    documentation = hardening.get("documentation")
    require(isinstance(documentation, dict), "documentation hardening is required")
    assert isinstance(documentation, dict)
    require(
        documentation.get("generated_state_file") == "docs/release-state.md",
        "generated release-state path is invalid",
    )
    require(
        documentation.get("source_manifest") == "release-manifest.json",
        "generated release-state source is invalid",
    )


def workflow_link(run_id: int) -> str:
    return f"[`{run_id}`](https://github.com/migao2006/tool/actions/runs/{run_id})"


def publication_commit_text(snapshot: dict[str, Any]) -> str:
    commit = snapshot.get("git_commit")
    if commit:
        return f"`{commit}`"
    return "未記錄於目前可用證據（不得推測）"


def render_model_header(manifest: dict[str, Any]) -> str:
    model = manifest["model_card"]
    snapshot = model["published_research_snapshot"]
    feature = model["latest_feature_dataset"]
    workflow = model["workflow"]
    return "\n".join(
        [
            MODEL_HEADER_START,
            (
                f"> 最後核對：{manifest['last_verified_date']}。OOS 驗證 workflow："
                f"{workflow_link(workflow['run_id'])}；最新具完整 artifact／provenance "
                "證據的橫截面研究推論 workflow："
                f"{workflow_link(snapshot['workflow_run_id'])}；最新特徵 workflow："
                f"{workflow_link(feature['workflow_run_id'])}；發布 commit："
                f"{publication_commit_text(snapshot)}。動態資料與阻塞現況見 "
                "[`docs/current-status.md`](docs/current-status.md)，部署證據邊界見 "
                "[`docs/release-state.md`](docs/release-state.md)。"
            ),
            "",
            "> 本區塊與下方具完整 artifact／provenance 證據的快照由 "
            "`release-manifest.json` 產生；請勿直接修改。",
            MODEL_HEADER_END,
        ]
    )


def render_model_snapshot(manifest: dict[str, Any]) -> str:
    snapshot = manifest["model_card"]["published_research_snapshot"]
    return "\n".join(
        [
            MODEL_SNAPSHOT_START,
            f"- Workflow：{workflow_link(snapshot['workflow_run_id'])}",
            f"- Feature workflow：{workflow_link(snapshot['feature_workflow_run_id'])}",
            f"- 發布 commit：{publication_commit_text(snapshot)}",
            f"- `prediction_run_id`：`{snapshot['prediction_run_id']}`",
            f"- `as_of_date`：`{snapshot['as_of_date']}`",
            f"- `decision_at`：`{snapshot['decision_at']}`",
            f"- Evaluation scope：`{snapshot['evaluation_scope']}`",
            f"- 預測列數：{snapshot['prediction_count']:,} 檔上市股票",
            (
                "- 政策動作："
                f"`CANDIDATE={snapshot['candidate_count']}`、"
                f"`WATCH={snapshot['watch_count']}`、"
                f"`NO_TRADE={snapshot['no_trade_count']:,}`"
            ),
            (
                "- 政策評估狀態："
                f"`MISSING_REQUIRED_DATA={snapshot['policy_input_missing_count']:,}`、"
                f"`VALIDATION_FAILED={snapshot['policy_validation_failed_count']}`、"
                f"`HARD_FAIL={snapshot['policy_hard_fail_count']}`"
            ),
            (
                "- 公開 API 資料品質："
                f"{snapshot['data_quality_warn_count']:,} 筆 `WARN`，"
                f"{snapshot['hard_fail_count']:,} 筆 hard fail"
            ),
            (
                "- Industry coverage："
                f"{snapshot['industry_non_null_count']:,}／{snapshot['prediction_count']:,}"
            ),
            (
                "- Decision gate rows："
                f"{snapshot['decision_gate_count']:,}；每檔固定 "
                f"{snapshot['decision_gates_per_prediction']} 層"
            ),
            f"- Feature artifact SHA-256：`{snapshot['feature_artifact_sha256']}`",
            f"- Model bundle SHA-256：`{snapshot['model_bundle_sha256']}`",
            f"- Prediction snapshot SHA-256：`{snapshot['snapshot_sha256']}`",
            f"- Snapshot artifact SHA-256：`{snapshot['snapshot_artifact_sha256']}`",
            (
                f"- GitHub artifact：`{snapshot['github_artifact_id']}`，digest "
                f"`{snapshot['github_artifact_digest']}`"
            ),
            "",
            (
                "模型 bundle 由最後一個 walk-forward fold 依固定規則建立，沒有用最新橫截面選模；"
                "相同 artifact、設定與 seed 的 bundle identity 可重現。這批資料是目前具完整 "
                "artifact／provenance 證據的回溯研究推論，"
                "不是新的 OOS 評估。Production API 的既有驗證紀錄顯示回傳 1,068 檔且每檔恰好 8 層 "
                "fail-closed 研究 gate；缺少可交易性、市場曝險或部位輸入時不得推測通過。舊發布欄位曾把 "
                f"{snapshot['legacy_persisted_no_trade_count']:,} 列記為 `NO_TRADE`；狀態稽核已將其權威語意"
                "重分類為 `MISSING_REQUIRED_DATA`，政策動作為空值。不得描述為正式候選股、"
                "即時可交易建議或獲利保證。"
            ),
            MODEL_SNAPSHOT_END,
        ]
    )


def render_status_header(manifest: dict[str, Any]) -> str:
    model = manifest["model_card"]
    snapshot = model["published_research_snapshot"]
    repository = manifest["repository_state"]
    staging = repository["environment_migration_history"]["staging"]
    production = repository["environment_migration_history"]["production"]
    hardening = manifest["platform_hardening"]
    snapshot_read = hardening["prediction_snapshot"]
    freshness = snapshot_read["freshness_policy"]
    p2_refactoring = hardening["p2_refactoring"]
    auth_recovery = hardening["auth_recovery"]
    ci = hardening["continuous_integration"]
    vercel = hardening["vercel"]
    patch_added = "、".join(f"`{name}`" for name in repository["patch_added_migrations"])
    remote_gap = "、".join(
        f"`{name}`" for name in repository["migrations_after_recorded_remote_latest"]
    )
    return "\n".join(
        [
            STATUS_HEADER_START,
            f"> 更新日期：{manifest['last_verified_date']}（Asia/Taipei）",
            ">",
            (
                "> 文件基準：最新發布 commit 未記錄於目前可用證據，不得沿用舊快照 commit；"
                f"OOS 驗證 workflow 使用 `{model['workflow']['run_id']}`，最新特徵與具完整 "
                "artifact／provenance 證據的研究推論 workflow 使用 "
                f"`{model['latest_feature_dataset']['workflow_run_id']}`、`{snapshot['workflow_run_id']}`"
            ),
            ">",
            f"> 系統狀態：`{model['status']}`",
            ">",
            (
                f"> Repository 目前包含 {repository['migration_file_count']} 個 migration 檔案；"
                f"本修補新增且待 Staging／Production 部署驗證：{patch_added}。"
            ),
            ">",
            (
                "> Staging／Production 的既有文件最後完整紀錄均為 "
                f"{staging['recorded_applied_count']}／{production['recorded_applied_count']} 筆；"
                f"其後 Repository 共有 {len(repository['migrations_after_recorded_remote_latest'])} 檔："
                f"{remote_gap}。本修補未連線重新驗證這些 migration 的遠端套用狀態，"
                "不得由檔案存在與否推測已部署或未部署。"
            ),
            ">",
            (
                "> Prediction Snapshot 主要讀取路徑已改為單一 RPC `"
                f"{snapshot_read['primary_read_path']}`，正常路徑預期每次快照只產生 "
                f"{snapshot_read['expected_primary_postgrest_requests']} 次 PostgREST 請求。"
                f"預設模式為 `{snapshot_read['default_mode']}`；RPC 未部署時 fail closed，"
                f"只有明確設定 `{snapshot_read['emergency_rollback_mode']}` 才走緊急舊路徑。"
            ),
            (
                "> Freshness 優先使用 `"
                f"{freshness['preferred_method']}`，要求 "
                f"{freshness['default_lookback_days']} 日連續可信日曆覆蓋（上限 "
                f"{freshness['maximum_lookback_days']} 日；RPC 取回 "
                f"{freshness['rpc_calendar_window_days']} 個曆日以涵蓋就緒時間前的邊界）；"
                f"缺日或不可用時明確改採 `{freshness['fallback_method']}`，不得猜測休市日。"
            ),
            (
                "> P2 已抽出 TWSE／TPEX 共用月度 benchmark 與 feature CLI 協調器，"
                f"並將三個核心入口函式控制在 {p2_refactoring['historical_backfill_run_lines']}、"
                f"{p2_refactoring['daily_inference_run_lines']}、"
                f"{p2_refactoring['research_dataset_from_frame_lines']} 行。"
            ),
            (
                f"> 帳號復原使用 `{auth_recovery['flow_type']}` 與 "
                f"`{auth_recovery['recovery_event']}`；Supabase Redirect URL allowlist 與正式 SMTP "
                "尚未由本修補連線重新驗證。"
            ),
            ">",
            (
                f"> CI 品質工作：`{ci['quality_job_id']}`；彙總 gate：`{ci['required_gate_job_id']}`；"
                "外部 GitHub Actions 全部固定完整 commit SHA。遠端 branch protection "
                "尚未由本修補重新驗證。"
            ),
            ">",
            (
                f"> Vercel 使用 `{vercel['config_file']}` 強制 CSP 與安全標頭；"
                "本修補尚未直接讀取正式站 response headers，因此遠端生效狀態不得推測。"
            ),
            ">",
            "> 本區塊與下方具完整 artifact／provenance 證據的快照由 "
            "`release-manifest.json` 產生；請勿直接修改。",
            STATUS_HEADER_END,
        ]
    )


def render_status_snapshot(manifest: dict[str, Any]) -> str:
    model = manifest["model_card"]
    snapshot = model["published_research_snapshot"]
    return "\n".join(
        [
            STATUS_SNAPSHOT_START,
            (
                f"[GitHub Actions run `{snapshot['workflow_run_id']}`]"
                f"({snapshot['workflow_url']}) 已使用該次已驗證特徵橫截面、最後一個 walk-forward fold "
                "的凍結模型 bundle，完成研究推論並發布至 Production Supabase；快照 RPC 與後續 "
                "gate attachment 的既有紀錄顯示已完成不可變讀回驗證。發布 commit 未記錄於目前可用證據，"
                "因此文件不再沿用舊快照 commit。"
            ),
            "",
            "| 項目 | 已驗證結果 |",
            "| --- | ---: |",
            f"| Evaluation scope | `{snapshot['evaluation_scope']}` |",
            f"| `as_of_date` | `{snapshot['as_of_date']}` |",
            f"| `decision_at` | `{snapshot['decision_at']}` |",
            f"| 預測列數 | {snapshot['prediction_count']:,} |",
            f"| Supabase `prediction_run_id` | {snapshot['prediction_run_id']} |",
            f"| Model version | `{model['model_version']}` |",
            f"| Training end date | `{model['training_end_date']}` |",
            (
                "| 政策動作 | "
                f"`CANDIDATE={snapshot['candidate_count']}`、"
                f"`WATCH={snapshot['watch_count']}`、"
                f"`NO_TRADE={snapshot['no_trade_count']:,}` |"
            ),
            (
                "| 政策評估狀態 | "
                f"`MISSING_REQUIRED_DATA={snapshot['policy_input_missing_count']:,}`、"
                f"`VALIDATION_FAILED={snapshot['policy_validation_failed_count']}`、"
                f"`HARD_FAIL={snapshot['policy_hard_fail_count']}` |"
            ),
            f"| 系統狀態 | `{snapshot['status']}` |",
            (
                "| 公開 API 資料品質 | "
                f"{snapshot['data_quality_warn_count']:,} 筆 `WARN`，"
                f"{snapshot['hard_fail_count']:,} 筆 hard fail |"
            ),
            (
                "| Industry coverage | "
                f"{snapshot['industry_non_null_count']:,}／{snapshot['prediction_count']:,} |"
            ),
            (
                "| Decision gate rows | "
                f"{snapshot['decision_gate_count']:,}；每檔固定 "
                f"{snapshot['decision_gates_per_prediction']} 層 |"
            ),
            "",
            (
                "完整性核對紀錄：股票與 global rank 均無重複、排名為 1～1,068 連續整數、"
                "三分類機率總和為 1、毛／淨 P10≤P50≤P90，且 "
                "`latest_available_at <= decision_at`。Provenance："
            ),
            "",
            f"- Feature artifact SHA-256：`{snapshot['feature_artifact_sha256']}`。",
            f"- Model bundle SHA-256：`{snapshot['model_bundle_sha256']}`。",
            f"- Prediction snapshot SHA-256：`{snapshot['snapshot_sha256']}`。",
            f"- Snapshot artifact SHA-256：`{snapshot['snapshot_artifact_sha256']}`。",
            (
                f"- GitHub artifact：`{snapshot['github_artifact_id']}`，digest "
                f"`{snapshot['github_artifact_digest']}`。"
            ),
            "",
            (
                "這是回溯研究推論，不是新的 OOS 驗證。既有契約驗證紀錄顯示每檔恰好 8 層 gate；"
                "gate order、actual、threshold、reason code 與 attachment snapshot hash 均通過。"
                "具備真實輸入的資料品質、流動性容量、校準方向機率、淨分位數及排名資格會顯示實際值與門檻；"
                "缺少 point-in-time 可交易性、市場模型及部位配置輸入時一律 fail closed。舊資料庫欄位"
                f"曾記錄 `NO_TRADE={snapshot['legacy_persisted_no_trade_count']:,}`；權威重分類為 "
                f"`MISSING_REQUIRED_DATA={snapshot['policy_input_missing_count']:,}` 且政策動作為空值。"
                "不得描述為正式候選股、即時交易訊號或獲利保證。"
            ),
            STATUS_SNAPSHOT_END,
        ]
    )


def replace_marked_or_section(
    text: str,
    start_marker: str,
    end_marker: str,
    replacement: str,
    fallback_start: str,
    fallback_end: str,
) -> str:
    marked = re.compile(
        re.escape(start_marker) + r".*?" + re.escape(end_marker),
        flags=re.DOTALL,
    )
    if marked.search(text):
        return marked.sub(replacement, text, count=1)
    start = text.find(fallback_start)
    end = text.find(fallback_end, start + len(fallback_start))
    if start < 0 or end < 0:
        raise ManifestError(
            f"could not locate documentation section between {fallback_start!r} and {fallback_end!r}"
        )
    content_start = start + len(fallback_start)
    return text[:content_start] + "\n\n" + replacement + "\n" + text[end:]


def render_release_state(manifest: dict[str, Any]) -> str:
    model = manifest["model_card"]
    snapshot = model["published_research_snapshot"]
    repository = manifest["repository_state"]
    hardening = manifest["platform_hardening"]
    snapshot_read = hardening["prediction_snapshot"]
    freshness = snapshot_read["freshness_policy"]
    p2_refactoring = hardening["p2_refactoring"]
    auth_recovery = hardening["auth_recovery"]
    ci = hardening["continuous_integration"]
    vercel = hardening["vercel"]
    histories = repository["environment_migration_history"]
    tools = ci["tools"]
    tool_rows = [f"| `{name}` | `{version}` |" for name, version in sorted(tools.items())]
    migration_rows = [
        f"- `{name}`" for name in repository["migrations_after_recorded_remote_latest"]
    ]
    patch_rows = [f"- `{name}`" for name in repository["patch_added_migrations"]]
    return (
        "\n".join(
            [
                "# Release 與部署證據狀態",
                "",
                "> 此文件完全由 `release-manifest.json` 產生；請勿直接修改。",
                f"> 最後核對日期：{manifest['last_verified_date']}（Asia/Taipei）。",
                f"> 證據基準：`{manifest['verification_basis']}`。",
                "",
                "## 模型與研究快照",
                "",
                "| 項目 | Manifest 記錄 |",
                "| --- | --- |",
                f"| 系統狀態 | `{model['status']}` |",
                f"| Model version | `{model['model_version']}` |",
                f"| Evidence scope | `{snapshot['evidence_scope']}` |",
                f"| Prediction run | `{snapshot['prediction_run_id']}` |",
                f"| Snapshot workflow | `{snapshot['workflow_run_id']}` |",
                f"| Snapshot commit | {publication_commit_text(snapshot)} |",
                f"| Evaluation scope | `{snapshot['evaluation_scope']}` |",
                f"| Prediction count | `{snapshot['prediction_count']}` |",
                (
                    "| Policy action counts | "
                    f"`CANDIDATE={snapshot['candidate_count']}`, "
                    f"`WATCH={snapshot['watch_count']}`, "
                    f"`NO_TRADE={snapshot['no_trade_count']}` |"
                ),
                (
                    "| Policy status counts | "
                    f"`MISSING_REQUIRED_DATA={snapshot['policy_input_missing_count']}`, "
                    f"`VALIDATION_FAILED={snapshot['policy_validation_failed_count']}`, "
                    f"`HARD_FAIL={snapshot['policy_hard_fail_count']}` |"
                ),
                "",
                "## Migration 證據邊界",
                "",
                f"Repository 目前共有 **{repository['migration_file_count']}** 個 migration 檔案。",
                "本修補新增、且仍須在隔離環境驗證後才能部署：",
                "",
                *patch_rows,
                "",
                (
                    "Staging 已記錄："
                    f"`{histories['staging']['recorded_applied_count']}` 個，最後為 "
                    f"`{histories['staging']['recorded_latest_migration']}`，證據狀態 "
                    f"`{histories['staging']['evidence_status']}`。"
                ),
                (
                    "Production 已記錄："
                    f"`{histories['production']['recorded_applied_count']}` 個，最後為 "
                    f"`{histories['production']['recorded_latest_migration']}`，證據狀態 "
                    f"`{histories['production']['evidence_status']}`。"
                ),
                "",
                "已記錄遠端最新 migration 之後的 Repository 檔案：",
                "",
                *migration_rows,
                "",
                "上述檔案存在不等於已套用至任何遠端環境。",
                "",
                "## P1／P2 執行控制",
                "",
                "### Prediction Snapshot",
                "",
                f"- 主要路徑：`{snapshot_read['primary_read_path']}`。",
                (
                    "- 正常 Edge→PostgREST 往返："
                    f"`{snapshot_read['expected_primary_postgrest_requests']}` 次。"
                ),
                f"- 預設模式：`{snapshot_read['default_mode']}`。",
                f"- 緊急回復模式：`{snapshot_read['emergency_rollback_mode']}`。",
                f"- 靜默 fallback：禁止；契約為 `{snapshot_read['fallback_condition']}`。",
                f"- 基礎 RPC migration：`{snapshot_read['base_migration']}`。",
                f"- Calendar v2 migration：`{snapshot_read['migration']}`。",
                f"- 遠端狀態：`{snapshot_read['remote_status']}`。",
                (
                    "- Decision Policy 部署順序：`"
                    + "` → `".join(snapshot_read["decision_policy_rollout_order"])
                    + "`。"
                ),
                (
                    "- Decision Policy 回復限制：`"
                    f"{snapshot_read['decision_policy_rollback_constraint']}`。"
                ),
                f"- Freshness 首選：`{freshness['preferred_method']}`。",
                f"- 日曆缺口處理：`{freshness['calendar_gap_behavior']}`。",
                (
                    "- 預設 freshness 參數：台北 "
                    f"`{freshness['default_ready_hour_taipei']}:00`、"
                    f"`{freshness['default_lookback_days']}` 日連續覆蓋（上限 "
                    f"`{freshness['maximum_lookback_days']}` 日；RPC 視窗 "
                    f"`{freshness['rpc_calendar_window_days']}` 個曆日）、"
                    f"`{freshness['fallback_stale_hours']}` 小時 fallback。"
                ),
                "",
                "### P2 共用協調器與複雜度控制",
                "",
                f"- 月度 benchmark 共用協調器：`{p2_refactoring['monthly_benchmark_orchestrator']}`。",
                f"- 場別 feature CLI 共用流程：`{p2_refactoring['venue_feature_cli_orchestrator']}`。",
                (
                    "- 核心入口行數：historical backfill "
                    f"`{p2_refactoring['historical_backfill_run_lines']}`、daily inference "
                    f"`{p2_refactoring['daily_inference_run_lines']}`、dataset assembly "
                    f"`{p2_refactoring['research_dataset_from_frame_lines']}`。"
                ),
                f"- 遠端狀態：`{p2_refactoring['remote_status']}`。",
                "",
                "### 帳號復原",
                "",
                f"- Provider：`{auth_recovery['provider']}`。",
                f"- OAuth/session flow：`{auth_recovery['flow_type']}`。",
                f"- Recovery event：`{auth_recovery['recovery_event']}`。",
                f"- Redirect policy：`{auth_recovery['redirect_policy']}`。",
                f"- Account enumeration response：`{auth_recovery['account_enumeration_response']}`。",
                f"- Redirect allowlist：`{auth_recovery['redirect_allowlist_status']}`。",
                f"- Production SMTP：`{auth_recovery['production_smtp_status']}`。",
                "",
                "### CI 與供應鏈",
                "",
                f"- 品質工作 ID：`{ci['quality_job_id']}`。",
                f"- 彙總 gate ID：`{ci['required_gate_job_id']}`。",
                f"- Branch protection：`{ci['branch_protection_status']}`。",
                f"- Action pin policy：`{ci['action_pin_policy']}`。",
                f"- 工具版本來源：`{ci['tool_version_file']}`。",
                "",
                "| 工具 | 固定版本 |",
                "| --- | --- |",
                *tool_rows,
                "",
                "### Vercel",
                "",
                f"- 設定檔：`{vercel['config_file']}`。",
                f"- CSP enforcement：`{str(vercel['csp_enforced']).lower()}`。",
                f"- Inline script allowed：`{str(vercel['inline_script_allowed']).lower()}`。",
                f"- Inline style allowed：`{str(vercel['inline_style_allowed']).lower()}`。",
                (
                    "- 正式站 response headers 已直接驗證："
                    f"`{str(vercel['remote_response_headers_verified']).lower()}`。"
                ),
                "",
                "## 部署限制",
                "",
                "本次交付只修改 Repository。不得把下列事項描述為已完成：",
                "",
                "- Staging／Production migration 已套用。",
                "- Edge Function 已更新。",
                "- Vercel Production 安全標頭已生效。",
                "- GitHub branch protection 已要求新的彙總 gate。",
                "",
                (
                    "Decision Policy 上線時必須先部署可同時理解 legacy 與新狀態契約的 Frontend／Edge，"
                    "再套用 status migration，最後部署 status-aware publisher；migration 套用後不得先回退 "
                    "Edge。基礎 RPC 與 calendar v2 migration 仍須依序套用並驗證；帳號復原上線前另須驗證 "
                    "Redirect URL allowlist 與正式 SMTP。"
                ),
            ]
        )
        + "\n"
    )


def expected_outputs(manifest: dict[str, Any]) -> dict[Path, str]:
    model_markdown = MODEL_CARD_MARKDOWN_PATH.read_text(encoding="utf-8")
    model_markdown = replace_marked_or_section(
        model_markdown,
        MODEL_HEADER_START,
        MODEL_HEADER_END,
        render_model_header(manifest),
        "# Alpha Lens 5 日短波段選股 MVP 模型卡\n",
        "\n## 狀態",
    )
    model_markdown = replace_marked_or_section(
        model_markdown,
        MODEL_SNAPSHOT_START,
        MODEL_SNAPSHOT_END,
        render_model_snapshot(manifest),
        "## 最新橫截面研究推論\n",
        "\n## 標籤與交易路徑",
    )
    model_markdown = model_markdown.replace(
        "## 最新橫截面研究推論",
        "## 最新具完整 artifact／provenance 證據的橫截面研究推論",
    )

    status_markdown = CURRENT_STATUS_PATH.read_text(encoding="utf-8")
    status_markdown = replace_marked_or_section(
        status_markdown,
        STATUS_HEADER_START,
        STATUS_HEADER_END,
        render_status_header(manifest),
        "# 目前實作與阻塞狀態\n",
        "\n## 一、環境與 Migration",
    )
    status_markdown = replace_marked_or_section(
        status_markdown,
        STATUS_SNAPSHOT_START,
        STATUS_SNAPSHOT_END,
        render_status_snapshot(manifest),
        "### 最新上市橫截面研究推論\n",
        "\n## 三、Supplemental 回補現況",
    )
    status_markdown = status_markdown.replace(
        "### 最新上市橫截面研究推論",
        "### 最新具完整 artifact／provenance 證據的上市橫截面研究推論",
    )

    manifest_bytes = MANIFEST_PATH.read_bytes()
    digest = hashlib.sha256(manifest_bytes).hexdigest()
    return {
        MODEL_CARD_JSON_PATH: json.dumps(manifest["model_card"], ensure_ascii=False, indent=2)
        + "\n",
        MODEL_CARD_MARKDOWN_PATH: model_markdown.rstrip() + "\n",
        CURRENT_STATUS_PATH: status_markdown.rstrip() + "\n",
        RELEASE_STATE_PATH: render_release_state(manifest),
        MANIFEST_DIGEST_PATH: f"{digest}  release-manifest.json\n",
    }


def synchronize(check: bool) -> int:
    manifest = load_manifest()
    outputs = expected_outputs(manifest)
    stale: list[str] = []
    for path, expected in outputs.items():
        actual = path.read_text(encoding="utf-8") if path.exists() else None
        if actual == expected:
            continue
        stale.append(str(path.relative_to(ROOT)))
        if not check:
            path.write_text(expected, encoding="utf-8")
    if stale and check:
        raise ManifestError("release manifest outputs are stale: " + ", ".join(stale))
    return len(stale)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Synchronize model provenance documents from release-manifest.json."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail instead of updating files when generated outputs are stale",
    )
    args = parser.parse_args()
    try:
        changed = synchronize(check=args.check)
    except (ManifestError, json.JSONDecodeError) as error:
        parser.error(str(error))
    if not args.check:
        print(f"synchronized {changed} release-manifest output(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
