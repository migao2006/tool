import { AuthController } from "./auth-controller.js?v=auth-8";
import { AuthDialog } from "../components/auth/auth-dialog.js?v=auth-8";
import { publicConfig } from "../core/public-config.js?v=auth-7";
import { createSupabaseClient } from "../data/supabase-client.js?v=auth-7";
import { createAuthService } from "../features/auth/auth-service.js?v=auth-6";

async function startAuth() {
  const root = document.querySelector("#auth-root");
  const entryRoot = document.querySelector("#auth-entry");
  if (!root || !entryRoot) return;

  const dialog = new AuthDialog(root, entryRoot);
  let service = null;

  try {
    const client = await createSupabaseClient(publicConfig);
    if (client) {
      service = createAuthService(
        client,
        publicConfig.authConfirmationRedirectUrl,
        publicConfig.authPasswordRecoveryRedirectUrl,
      );
    }
  } catch (error) {
    globalThis.Sentry?.captureException?.(error);
  }

  const controller = new AuthController(dialog, service);
  controller.start();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", startAuth, { once: true });
} else {
  startAuth();
}
