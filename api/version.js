import packageJson from "../package.json" with { type: "json" };
import { V20_MODEL_VERSION } from "../supabase/functions/_shared/v20-opportunity-policy.js";

const NO_STORE = "no-store, no-cache, max-age=0, must-revalidate";
const SHA_PATTERN = /^[0-9a-f]{7,64}$/i;
const SAFE_IDENTIFIER = /^[a-zA-Z0-9._:-]{1,160}$/;
const SAFE_HOSTNAME = /^(?=.{1,253}$)[a-zA-Z0-9.-]+$/;

function safeValue(value, pattern = SAFE_IDENTIFIER) {
  const normalized = String(value || "").trim();
  return pattern.test(normalized) ? normalized : null;
}

function sourceState(env, sha, sourceType) {
  const declared = String(env.TWSS_SOURCE_STATE || "").trim().toLowerCase();
  const dirtyFlag = String(env.VERCEL_GIT_DIRTY || env.GIT_DIRTY || "").trim().toLowerCase();
  if (declared === "dirty" || ["1", "true", "yes"].includes(dirtyFlag)) return "dirty";
  if (declared === "unknown") return "unknown";
  if (declared === "clean") return sha ? "clean" : "unknown";
  if (sourceType === "vercel-git" || sourceType === "github-actions") return sha ? "clean" : "unknown";
  return "unknown";
}

export function versionPayload(env = process.env) {
  const vercelSha = safeValue(env.VERCEL_GIT_COMMIT_SHA, SHA_PATTERN);
  const vercelProvider = safeValue(env.VERCEL_GIT_PROVIDER);
  const vercelRef = safeValue(env.VERCEL_GIT_COMMIT_REF);
  const githubSha = safeValue(env.GITHUB_SHA, SHA_PATTERN);
  const declaredSha = safeValue(env.TWSS_GIT_SHA, SHA_PATTERN);
  const gitSha = vercelSha || githubSha || declaredSha;
  const sourceType = vercelSha && vercelProvider && vercelRef
    ? "vercel-git"
    : vercelSha
      ? "vercel-metadata"
      : githubSha
        ? "github-actions"
        : declaredSha
          ? "declared"
          : "unknown";

  return {
    release: String(packageJson.version),
    model: String(V20_MODEL_VERSION),
    gitSha,
    deployment: {
      id: safeValue(env.VERCEL_DEPLOYMENT_ID),
      environment: safeValue(env.VERCEL_TARGET_ENV || env.VERCEL_ENV),
      region: safeValue(env.VERCEL_REGION),
      hostname: safeValue(env.VERCEL_URL, SAFE_HOSTNAME),
    },
    source: {
      type: sourceType,
      state: sourceState(env, gitSha, sourceType),
    },
  };
}

function responseHeaders() {
  return {
    "cache-control": NO_STORE,
    "cdn-cache-control": "no-store",
    "vercel-cdn-cache-control": "no-store",
    "content-type": "application/json; charset=utf-8",
    "x-content-type-options": "nosniff",
  };
}

export default {
  fetch(request) {
    const method = request?.method || "GET";
    if (!["GET", "HEAD"].includes(method)) {
      return new Response(JSON.stringify({ error: "method_not_allowed" }), {
        status: 405,
        headers: { ...responseHeaders(), allow: "GET, HEAD" },
      });
    }
    return new Response(method === "HEAD" ? null : JSON.stringify(versionPayload()), {
      status: 200,
      headers: responseHeaders(),
    });
  },
};

export const versionInternals = { NO_STORE, safeValue, sourceState };
