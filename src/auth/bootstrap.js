import { AuthController } from "./auth-controller.js";
import { AuthDialog } from "../components/auth/auth-dialog.js";
import { publicConfig } from "../core/public-config.js";
import { createSupabaseClient } from "../data/supabase-client.js";
import { createAuthService } from "../features/auth/auth-service.js";

function startAuth() {
  const root = document.querySelector("#auth-root");
  const entryRoot = document.querySelector("#auth-entry");
  if (!root || !entryRoot) return;

  const dialog = new AuthDialog(root, entryRoot);
  let service = null;

  try {
    const client = createSupabaseClient(publicConfig);
    if (client) service = createAuthService(client, publicConfig.authRedirectUrl);
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
