import { readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = resolve(fileURLToPath(new URL("..", import.meta.url)));
const read = (path) => readFile(resolve(projectRoot, path), "utf8");

const [page, app, patch, smart, v20, styles, manifest, icon, serviceWorker, latestData, backtestData, dailyReportData, backendSource, deepDataSource, backendStoreSource] =
  await Promise.all([
    read("public/index.html"),
    read("public/app.js"),
    read("public/patch.js"),
    read("public/smart.js"),
    read("public/v20.js"),
    read("public/styles.css"),
    read("public/manifest.webmanifest"),
    read("public/icon.svg"),
    read("public/sw.js"),
    read("public/data/latest.json"),
    read("public/data/backtest.json"),
    read("public/data/daily-report.json"),
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
  `const V20=${literal(v20)};`,
  `const STYLES=${literal(styles)};`,
  `const MANIFEST=${literal(manifest)};`,
  `const ICON=${literal(icon)};`,
  `const SERVICE_WORKER=${literal(serviceWorker)};`,
  `const LATEST_DATA=${literal(latestData)};`,
  `const BACKTEST_DATA=${literal(backtestData)};`,
  `const DAILY_REPORT_DATA=${literal(dailyReportData)};`,
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

const workerSecretEncoder=new TextEncoder();
let workerMaintenanceCache={baseUrl:"",failClosed:true,expiresAt:0,state:null};

function runtimeEnv(env,name){
  return String(env?.[name]??globalThis.process?.env?.[name]??"").trim();
}

function enabledEnv(value){
  return /^(?:1|true|yes|on|enabled)$/i.test(String(value||"").trim());
}

async function sha256Secret(value){
  return new Uint8Array(await crypto.subtle.digest("SHA-256",workerSecretEncoder.encode(String(value))));
}

async function constantTimeSecretEqual(left,right){
  if(!left||!right)return false;
  const [leftHash,rightHash]=await Promise.all([sha256Secret(left),sha256Secret(right)]);
  let difference=0;
  for(let index=0;index<leftHash.length;index+=1)difference|=leftHash[index]^rightHash[index];
  return difference===0;
}

async function authorizeInternalRefresh(request,env){
  const configuredSecret=runtimeEnv(env,"TWSS_INTERNAL_REFRESH_TOKEN");
  if(request.method!=="POST"||!configuredSecret)return false;
  return constantTimeSecretEqual(request.headers.get("x-twss-refresh-token")||"",configuredSecret);
}

function workerJson(payload,status,headers={}){
  return new Response(JSON.stringify(payload),{status,headers:{
    "content-type":"application/json; charset=utf-8",
    "cache-control":"no-store, max-age=0",
    ...headers
  }});
}

async function workerMaintenanceState(env){
  if(enabledEnv(runtimeEnv(env,"MAINTENANCE_MODE"))){
    return {enabled:true,phase:"maintenance",reason:"forced_by_environment",generation:null};
  }
  const baseUrl=(runtimeEnv(env,"MARKET_SUPABASE_URL")||runtimeEnv(env,"SUPABASE_URL")).replace(/\\\/$/,"");
  const serviceKey=runtimeEnv(env,"MARKET_SUPABASE_SERVICE_ROLE_KEY")||runtimeEnv(env,"SUPABASE_SERVICE_ROLE_KEY");
  const failClosed=!/^(?:0|false|no|off|disabled)$/i.test(runtimeEnv(env,"MAINTENANCE_FAIL_CLOSED"));
  if(!baseUrl||!serviceKey){
    return {enabled:failClosed,phase:failClosed?"configuration_missing":"off",generation:null};
  }
  const now=Date.now();
  if(workerMaintenanceCache.baseUrl===baseUrl&&workerMaintenanceCache.failClosed===failClosed&&workerMaintenanceCache.state&&workerMaintenanceCache.expiresAt>now){
    return workerMaintenanceCache.state;
  }
  try{
    const headers={apikey:serviceKey,accept:"application/json"};
    if(!serviceKey.startsWith("sb_"))headers.authorization="Bearer "+serviceKey;
    const response=await fetch(baseUrl+"/rest/v1/twss_maintenance_control?id=eq.global&select=enabled,phase,reason,generation,updated_at",{
      headers,
      cache:"no-store",
      signal:AbortSignal.timeout(1500)
    });
    if(!response.ok)throw new Error("maintenance control returned "+response.status);
    const payload=await response.json();
    const row=Array.isArray(payload)?payload[0]:payload;
    if(!row||typeof row.enabled!=="boolean")throw new Error("maintenance status row missing or invalid");
    const state={
      enabled:row.enabled,
      phase:row?.phase||"off",
      reason:row?.reason||null,
      generation:Number.isFinite(Number(row?.generation))?Number(row.generation):null,
      updatedAt:row?.updated_at||null
    };
    workerMaintenanceCache={baseUrl,failClosed,expiresAt:now+2500,state};
    return state;
  }catch{
    const state={enabled:failClosed,phase:"status_unavailable",generation:null};
    workerMaintenanceCache={baseUrl,failClosed,expiresAt:now+2500,state};
    return state;
  }
}

function workerMaintenanceResponse(url,state){
  const headers={
    "cache-control":"no-store, max-age=0",
    "retry-after":"300",
    "x-maintenance-phase":state.phase||"maintenance"
  };
  if(url.pathname.startsWith("/api/")){
    return workerJson({
      ok:false,
      code:"MAINTENANCE",
      message:"系統維護中，請稍後再試。",
      phase:state.phase||"maintenance",
      generation:state.generation??null
    },503,headers);
  }
  return new Response('<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>系統維護中</title><body><main><h1>系統維護中</h1><p>服務正在更新，請稍後再試。</p></main></body></html>',{
    status:503,
    headers:{...headers,"content-type":"text/html; charset=utf-8"}
  });
}

async function handleWorkerMarketData(request,url,env){
  const refreshRequested=url.searchParams.get("refresh")==="1";
  if(refreshRequested){
    if(!await authorizeInternalRefresh(request,env)){
      return workerJson({error:"refresh_forbidden",code:"REFRESH_FORBIDDEN"},403);
    }
  }else if(request.method!=="GET"){
    return workerJson({error:"method_not_allowed",code:"METHOD_NOT_ALLOWED"},405,{allow:"GET"});
  }
  return handleMarketData(request,url);
}

export default {
  async fetch(request,env={}){
    const url=new URL(request.url);
    const path=url.pathname;
    const maintenance=await workerMaintenanceState(env);
    if(maintenance.enabled)return workerMaintenanceResponse(url,maintenance);
    if(path==="/api/market-data")return handleWorkerMarketData(request,url,env);
    if(path==="/api/health")return Response.json(healthPayload(),{headers:{"cache-control":"no-store, max-age=0"}});
    if(path==="/")return new Response(PAGE,{headers:{
      ...securityHeaders("text/html; charset=utf-8","no-cache, no-store, must-revalidate"),
      "content-security-policy":"default-src 'self'; connect-src 'self' https://gxwrczuwshndnjactrij.supabase.co https://lfkdkdyaatdlizryiyon.supabase.co; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    }});
    if(path==="/app.js")return new Response(APP,{headers:securityHeaders("text/javascript; charset=utf-8")});
    if(path==="/patch.js")return new Response(PATCH,{headers:securityHeaders("text/javascript; charset=utf-8")});
    if(path==="/smart.js")return new Response(SMART,{headers:securityHeaders("text/javascript; charset=utf-8")});
    if(path==="/v20.js")return new Response(V20,{headers:securityHeaders("text/javascript; charset=utf-8")});
    if(path==="/styles.css")return new Response(STYLES,{headers:securityHeaders("text/css; charset=utf-8")});
    if(path==="/manifest.webmanifest")return new Response(MANIFEST,{headers:securityHeaders("application/manifest+json; charset=utf-8")});
    if(path==="/icon.svg")return new Response(ICON,{headers:securityHeaders("image/svg+xml; charset=utf-8")});
    if(path==="/sw.js")return new Response(SERVICE_WORKER,{headers:securityHeaders("text/javascript; charset=utf-8","no-cache, no-store, must-revalidate")});
    if(path==="/data/latest.json")return new Response(LATEST_DATA,{headers:securityHeaders("application/json; charset=utf-8","no-store, max-age=0")});
    if(path==="/data/backtest.json")return new Response(BACKTEST_DATA,{headers:securityHeaders("application/json; charset=utf-8","no-store, max-age=0")});
    if(path==="/data/daily-report.json")return new Response(DAILY_REPORT_DATA,{headers:securityHeaders("application/json; charset=utf-8","no-store, max-age=0")});
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
