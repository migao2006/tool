import { readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = resolve(fileURLToPath(new URL("..", import.meta.url)));
const read = (path) => readFile(resolve(projectRoot, path), "utf8");

const [page, app, patch, smart, styles, manifest, icon, serviceWorker, latestData, backtestData, backendSource, deepDataSource, backendStoreSource] =
  await Promise.all([
    read("public/index.html"),
    read("public/app.js"),
    read("public/patch.js"),
    read("public/smart.js"),
    read("public/styles.css"),
    read("public/manifest.webmanifest"),
    read("public/icon.svg"),
    read("public/sw.js"),
    read("public/data/latest.json"),
    read("public/data/backtest.json"),
    read("src/market-data.js"),
    read("src/deep-data.js"),
    read("src/backend-store.js"),
  ]);

const backend = backendSource.replace(/^export\s+(?=(?:async\s+)?function\s)/gm, "");
const literal = (value) => JSON.stringify(value);

const worker = `${[
  `const PAGE=${literal(page)};`,
  `const APP=${literal(app)};`,
  `const PATCH=${literal(patch)};`,
  `const SMART=${literal(smart)};`,
  `const STYLES=${literal(styles)};`,
  `const MANIFEST=${literal(manifest)};`,
  `const ICON=${literal(icon)};`,
  `const SERVICE_WORKER=${literal(serviceWorker)};`,
  `const LATEST_DATA=${literal(latestData)};`,
  `const BACKTEST_DATA=${literal(backtestData)};`,
].join("\n")}

${backend}

function securityHeaders(contentType,cache="public, max-age=3600"){
  return {
    "content-type":contentType,
    "cache-control":cache,
    "x-content-type-options":"nosniff",
    "referrer-policy":"strict-origin-when-cross-origin",
    "permissions-policy":"camera=(), microphone=(), geolocation=()"
  };
}

export default {
  async fetch(request){
    const url=new URL(request.url);
    const path=url.pathname;
    if(path==="/api/market-data")return handleMarketData(request,url);
    if(path==="/api/health")return Response.json(healthPayload(),{headers:{"cache-control":"no-store, max-age=0"}});
    if(path==="/")return new Response(PAGE,{headers:{
      ...securityHeaders("text/html; charset=utf-8","no-cache, no-store, must-revalidate"),
      "content-security-policy":"default-src 'self'; connect-src 'self' https://gxwrczuwshndnjactrij.supabase.co https://lfkdkdyaatdlizryiyon.supabase.co; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    }});
    if(path==="/app.js")return new Response(APP,{headers:securityHeaders("text/javascript; charset=utf-8")});
    if(path==="/patch.js")return new Response(PATCH,{headers:securityHeaders("text/javascript; charset=utf-8")});
    if(path==="/smart.js")return new Response(SMART,{headers:securityHeaders("text/javascript; charset=utf-8")});
    if(path==="/styles.css")return new Response(STYLES,{headers:securityHeaders("text/css; charset=utf-8")});
    if(path==="/manifest.webmanifest")return new Response(MANIFEST,{headers:securityHeaders("application/manifest+json; charset=utf-8")});
    if(path==="/icon.svg")return new Response(ICON,{headers:securityHeaders("image/svg+xml; charset=utf-8")});
    if(path==="/sw.js")return new Response(SERVICE_WORKER,{headers:securityHeaders("text/javascript; charset=utf-8","no-cache, no-store, must-revalidate")});
    if(path==="/data/latest.json")return new Response(LATEST_DATA,{headers:securityHeaders("application/json; charset=utf-8","no-store, max-age=0")});
    if(path==="/data/backtest.json")return new Response(BACKTEST_DATA,{headers:securityHeaders("application/json; charset=utf-8","no-store, max-age=0")});
    return new Response("Not found",{status:404,headers:securityHeaders("text/plain; charset=utf-8","no-store")});
  }
};
`;

await writeFile(resolve(projectRoot, "worker/index.js"), worker);
// Keep the imported deep-data module next to the generated worker.  This avoids
// fragile source concatenation (the modules intentionally have private helper
// names in common) while still producing a self-contained deployable folder.
await writeFile(resolve(projectRoot, "worker/deep-data.js"), deepDataSource);
await writeFile(resolve(projectRoot, "worker/backend-store.js"), backendStoreSource);
console.log("Generated worker/index.js from readable source files");
