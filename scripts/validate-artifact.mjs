import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const projectRoot = resolve(fileURLToPath(new URL("..", import.meta.url)));
const workerPath = resolve(projectRoot, "dist/server/index.js");
const manifestPath = resolve(projectRoot, "dist/.openai/hosting.json");

const source = await readFile(workerPath, "utf8");

// The manifest belongs to ChatGPT Sites and is not required by GitHub/Vercel.
// Validate it when present, while keeping this exported project standalone.
try {
  await access(manifestPath);
  JSON.parse(await readFile(manifestPath, "utf8"));
} catch (error) {
  if (error?.code !== "ENOENT") throw error;
}

// Import from its real path so the generated worker can resolve its colocated
// deep-data module.  The project package.json declares ESM for dist/ as well.
const workerModule = await import(`${pathToFileURL(workerPath)}?validate=${Date.now()}`);
assert.equal(
  typeof workerModule.default?.fetch,
  "function",
  `${pathToFileURL(workerPath)} must export default.fetch`,
);

console.log("Artifact is valid ESM and exports default.fetch");
