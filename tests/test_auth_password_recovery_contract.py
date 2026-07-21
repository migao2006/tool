from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_supabase_auth_uses_pkce_and_same_origin_recovery_redirect() -> None:
    client = read("src/data/supabase-client.js")
    service = read("src/features/auth/auth-service.js")
    config = read("src/core/public-config.js")

    assert 'flowType: "pkce"' in client
    assert "detectSessionInUrl: true" in client
    assert "target.origin !== globalThis.location.origin" in service
    assert "resetPasswordForEmail(email" in service
    assert "redirectTo: recoveryRedirect" in service
    assert "updateUser({ password })" in service
    assert 'authRedirectUrl("password-recovery")' in config


def test_recovery_controller_is_event_bound_and_prevents_account_enumeration() -> None:
    controller = read("src/auth/auth-controller.js")
    template = read("src/components/auth/auth-template.js")

    assert 'event === "PASSWORD_RECOVERY"' in controller
    assert "if (!this.recoveryMode)" in controller
    assert "sanitizeAuthCallbackUrl" in controller
    assert "若此 Email 有帳號" in controller
    assert "captureException" in controller
    assert "不會透露此 Email 是否已註冊" in template
    assert 'data-auth-form="request-reset"' in template
    assert 'data-auth-form="update-password"' in template


def test_router_does_not_overwrite_unprocessed_implicit_auth_fragment() -> None:
    callback = read("src/features/auth/auth-callback.js")
    router = read("src/core/router.js")

    for sensitive_key in ("access_token", "refresh_token", "error_description"):
        assert f'"{sensitive_key}"' in callback
    assert "AUTH_QUERY_TRIGGER_KEYS" in callback
    assert 'key !== "state"' in callback
    assert "hasImplicitAuthCallback" in router
    assert "const authCallbackPending = hasImplicitAuthCallback();" in router
    assert "!authCallbackPending && updateHash" in router
