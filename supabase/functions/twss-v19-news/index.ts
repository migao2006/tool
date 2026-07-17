// v19 official material-information synchronizer.  This worker is independent
// from market ranking jobs: either system can fail without blocking the other.
// @ts-ignore Shared normalizer is plain ESM and is also exercised by Node tests.
import {
  filterChangedDisclosures,
  normalizeOfficialFeed,
  OFFICIAL_NEWS_SOURCES,
} from "../_shared/v19-news.js";
// @ts-ignore Shared guard is plain ESM and covered by Node regression tests.
import {
  maintenanceDisposition,
  maintenanceSkipPayload,
} from "../_shared/maintenance-guard.js";

const PROJECT_URL = Deno.env.get("SUPABASE_URL") || "";
const JOB_KEY = "v19_news";
const now = () => new Date().toISOString();
const taipeiDate = () => new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Taipei",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
}).format(new Date());

function adminKey() {
  try {
    const keys = JSON.parse(Deno.env.get("SUPABASE_SECRET_KEYS") || "{}");
    if (keys.default) return String(keys.default);
  } catch {}
  return Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
}

const ADMIN_KEY = adminKey();
const json = (payload: unknown, status = 200) => new Response(JSON.stringify(payload), {
  status,
  headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
});

async function rest(path: string, options: {
  method?: string;
  body?: unknown;
  prefer?: string;
} = {}) {
  if (!PROJECT_URL || !ADMIN_KEY) throw new Error("Supabase backend environment is incomplete");
  const headers: Record<string, string> = {
    accept: "application/json",
    "content-type": "application/json",
    apikey: ADMIN_KEY,
  };
  if (!ADMIN_KEY.startsWith("sb_secret_")) headers.authorization = `Bearer ${ADMIN_KEY}`;
  if (options.prefer) headers.prefer = options.prefer;
  const response = await fetch(`${PROJECT_URL}/rest/v1/${path}`, {
    method: options.method || "GET",
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
  if (!response.ok) throw new Error(`Database ${response.status}: ${(await response.text()).slice(0, 300)}`);
  if (response.status === 204) return { data: null, response };
  const text = await response.text();
  return { data: text ? JSON.parse(text) : null, response };
}

async function verifyRequest(request: Request) {
  const token = request.headers.get("x-twss-sync-token") || "";
  if (!token) return false;
  const { data } = await rest("rpc/twss_verify_sync_token", {
    method: "POST",
    body: { p_token: token },
  });
  return data === true;
}

async function patchState(values: Record<string, unknown>) {
  await rest(`stock_sync_state?job_key=eq.${JOB_KEY}`, {
    method: "PATCH",
    body: { ...values, updated_at: now() },
    prefer: "return=minimal",
  });
}

async function claimLease(owner: string) {
  const { data } = await rest("rpc/twss_claim_sync_lease", {
    method: "POST",
    body: { p_job_key: JOB_KEY, p_owner: owner, p_seconds: 180 },
  });
  return data === true;
}

async function releaseLease(owner: string) {
  await rest("rpc/twss_release_sync_lease", {
    method: "POST",
    body: { p_job_key: JOB_KEY, p_owner: owner },
  });
}

async function fetchSource(source: typeof OFFICIAL_NEWS_SOURCES[number]) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 25_000);
  try {
    const response = await fetch(source.url, {
      headers: { accept: "application/json" },
      signal: controller.signal,
    });
    if (!response.ok) throw new Error(`Official source HTTP ${response.status}`);
    return await normalizeOfficialFeed(await response.json(), source, now());
  } finally {
    clearTimeout(timeout);
  }
}

async function upsertRows(rows: Record<string, unknown>[]) {
  for (let index = 0; index < rows.length; index += 200) {
    await rest("v19_news_items?on_conflict=source,external_id", {
      method: "POST",
      body: rows.slice(index, index + 200),
      prefer: "resolution=merge-duplicates,return=minimal",
    });
  }
}

async function existingContentRows() {
  const results = await Promise.all(OFFICIAL_NEWS_SOURCES.map(async (source) => {
    const { data } = await rest(
      `v19_news_items?select=source,external_id,content_hash&source=eq.${encodeURIComponent(source.id)}` +
      "&order=published_at.desc&limit=2000",
    );
    return Array.isArray(data) ? data : [];
  }));
  return results.flat();
}

Deno.serve(async (request) => {
  if (request.method !== "POST") return json({ error: "method_not_allowed" }, 405);
  if (!await verifyRequest(request).catch(() => false)) return json({ error: "unauthorized" }, 401);

  const maintenance = await maintenanceDisposition(rest);
  if (maintenance.blocked) return json(maintenanceSkipPayload(maintenance), maintenance.status);

  const owner = crypto.randomUUID();
  if (!await claimLease(owner)) return json({ status: "skipped", reason: "active_lease" }, 202);

  try {
    await patchState({
      status: "running",
      cycle_date: taipeiDate(),
      processed_count: 0,
      total_items: 0,
      started_at: now(),
      last_error: null,
    });

    const results = await Promise.allSettled(OFFICIAL_NEWS_SOURCES.map(fetchSource));
    const succeeded = results.flatMap((result) =>
      result.status === "fulfilled" ? [result.value] : []);
    if (!succeeded.length) throw new Error("All official disclosure sources are unavailable");

    const uniqueRows = new Map<string, Record<string, unknown>>();
    succeeded.flat().forEach((row) => {
      if (!row) return;
      uniqueRows.set(`${row.source}:${row.external_id}`, row);
    });
    const rows = [...uniqueRows.values()];
    const existing = await existingContentRows();
    const { changed: changedRows, unchanged: unchangedRows } =
      filterChangedDisclosures(rows, existing);
    await upsertRows(changedRows);

    const failedSources = results.flatMap((result, index) => result.status === "rejected"
      ? [OFFICIAL_NEWS_SOURCES[index].id]
      : []);
    const status = failedSources.length ? "partial" : "success";
    await patchState({
      status,
      cycle_date: taipeiDate(),
      processed_count: rows.length,
      total_items: rows.length,
      last_success_at: now(),
      last_error: null,
      details: {
        version: "19.0",
        sourceCounts: Object.fromEntries(succeeded.map((rows) => [
          String(rows[0]?.source || "official"),
          rows.length,
        ])),
        writtenRows: changedRows.length,
        unchangedRows,
        failedSources,
      },
    });
    return json({
      status,
      rows: rows.length,
      writtenRows: changedRows.length,
      unchangedRows,
      failedSources,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    await patchState({
      status: "error",
      last_error: message.slice(0, 1_000),
    }).catch(() => undefined);
    return json({ status: "error", code: "official_news_sync_failed" }, 502);
  } finally {
    await releaseLease(owner).catch(() => undefined);
  }
});
