import { access, copyFile, mkdir, rm } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const distRoot = path.join(projectRoot, "dist");

await mkdir(path.join(projectRoot, "worker"), { recursive: true });
await import("./generate-worker.mjs");
await rm(distRoot, { recursive: true, force: true });
await mkdir(path.join(distRoot, "server"), { recursive: true });

for (const file of ["index.js", "deep-data.js", "backend-store.js"]) {
  await copyFile(path.join(projectRoot, "worker", file), path.join(distRoot, "server", file));
}

const hostingFile = path.join(projectRoot, ".openai", "hosting.json");
try {
  await access(hostingFile);
  await mkdir(path.join(distRoot, ".openai"), { recursive: true });
  await copyFile(hostingFile, path.join(distRoot, ".openai", "hosting.json"));
} catch {
  // GitHub/Vercel exports intentionally do not require a Sites manifest.
}

console.log(`Built ${distRoot}`);
