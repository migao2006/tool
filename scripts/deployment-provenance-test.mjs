import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(fileURLToPath(new URL("..", import.meta.url)));
const workflowRoot = resolve(root, ".github/workflows");
const workflowNames = (await readdir(workflowRoot)).filter((name) => /\.ya?ml$/i.test(name));
const workflows = new Map(await Promise.all(workflowNames.map(async (name) => [
  name,
  await readFile(resolve(workflowRoot, name), "utf8"),
])));

assert.ok(workflows.has("ci.yml"), "PR/main verification workflow is required");
const ci = workflows.get("ci.yml");
assert.match(ci, /pull_request:/, "CI must run for pull requests");
assert.match(ci, /push:\s*[\s\S]*?branches:\s*[\s\S]*?- main/, "CI must run for pushes to main");
assert.match(ci, /node-version:\s*24\b/, "CI must use Node 24");
assert.match(ci, /npm ci\b/, "CI must use the lockfile");
assert.match(ci, /npm run build\b/, "CI must build the application");
assert.match(ci, /npm run validate\b/, "CI must validate the build artifact");
assert.match(ci, /npm run test:all\b/, "CI must run the full test suite without rebuilding twice");

const snapshots = workflows.get("update-market-data.yml");
assert.ok(snapshots, "snapshot workflow is required");
assert.match(snapshots, /actions\/upload-artifact@v4/, "validated snapshots must be retained as artifacts");
assert.match(snapshots, /gh pr create/, "snapshot changes must enter main through a pull request");
assert.match(snapshots, /refs\/heads\/\$branch/, "snapshot pushes must target an isolated automation branch");
assert.doesNotMatch(snapshots, /git push(?:\s+origin)?\s+(?:HEAD:)?(?:refs\/heads\/)?main\b/i,
  "scheduled snapshots must never push directly to main");

for (const [name, workflow] of workflows) {
  for (const match of workflow.matchAll(/node-version:\s*['\"]?([^\s'\"]+)/g)) {
    assert.match(match[1], /^24(?:\.x)?$/, `${name} must use Node 24`);
  }
  assert.doesNotMatch(workflow, /\bvercel\s+(?:deploy\s+)?--prod\b/i,
    `${name} must not bypass the Vercel Git production path`);
  assert.doesNotMatch(workflow, /\bvercel\s+deploy\b[^\n]*\b--prod\b/i,
    `${name} must not deploy production directly`);
}

const { default: versionRoute, versionPayload } = await import("../api/version.js");
const sha = "a".repeat(40);
const clean = versionPayload({
  VERCEL_GIT_COMMIT_SHA: sha,
  VERCEL_GIT_PROVIDER: "github",
  VERCEL_GIT_COMMIT_REF: "main",
  VERCEL_ENV: "production",
  VERCEL_DEPLOYMENT_ID: "dpl_test-123",
  VERCEL_REGION: "hnd1",
  VERCEL_URL: "smart-test.vercel.app",
  SUPABASE_SERVICE_ROLE_KEY: "must-never-appear",
  FINMIND_TOKEN: "must-never-appear-either",
});
assert.equal(clean.gitSha, sha);
assert.equal(clean.source.type, "vercel-git");
assert.equal(clean.source.state, "clean");
assert.equal(clean.model, "20.2");
assert.equal(clean.deployment.environment, "production");
assert.doesNotMatch(JSON.stringify(clean), /must-never-appear/, "version payload must not leak environment secrets");

const ambiguousVercelMetadata = versionPayload({ VERCEL_GIT_COMMIT_SHA: sha });
assert.equal(ambiguousVercelMetadata.source.type, "vercel-metadata");
assert.equal(ambiguousVercelMetadata.source.state, "unknown",
  "a SHA without Git-trigger metadata must not be claimed as a clean Git deployment");

const dirty = versionPayload({ TWSS_GIT_SHA: sha, TWSS_SOURCE_STATE: "dirty" });
assert.equal(dirty.gitSha, sha);
assert.equal(dirty.source.state, "dirty");

const unknown = versionPayload({
  TWSS_GIT_SHA: "not-a-sha",
  VERCEL_DEPLOYMENT_ID: "contains whitespace",
  VERCEL_URL: "https://not-a-hostname.example",
});
assert.equal(unknown.gitSha, null);
assert.equal(unknown.source.type, "unknown");
assert.equal(unknown.source.state, "unknown");
assert.equal(unknown.deployment.id, null);
assert.equal(unknown.deployment.hostname, null);

const getResponse = versionRoute.fetch(new Request("https://app.test/api/version"));
assert.equal(getResponse.status, 200);
assert.match(getResponse.headers.get("cache-control"), /no-store/);
assert.equal(getResponse.headers.get("vercel-cdn-cache-control"), "no-store");
const methodResponse = versionRoute.fetch(new Request("https://app.test/api/version", { method: "POST" }));
assert.equal(methodResponse.status, 405);
assert.equal(methodResponse.headers.get("allow"), "GET, HEAD");

console.log("Deployment governance and provenance contract: passed");
