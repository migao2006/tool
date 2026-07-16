# 台股智選 v20：DB-first 部署後驗證與回滾

本清單只適用於既有 MARKET Supabase 專案的向後相容升級。不要在 CORE 專案執行，也不要使用 `db reset --linked`。所有查詢應由已授權的資料庫管理員在 Supabase SQL Editor 執行；畫面、日誌、Issue 與對話中不得貼出任何金鑰、JWT、Vault 明文或連線字串。

## 1. 上線順序與通過條件

建議依序部署：

1. 套用 migration `20260716101225_add_db_first_enrichment_pipeline.sql`。
2. 部署 `twss-sync-batch` 與 `twss-v20-model` Edge Functions。
3. 確認 Cron、佇列與租約檢查全部通過。
4. 部署 Vercel API/UI。
5. 確認 Base 同日發布後，再觀察 Enrichment 背景補齊。

上線完成的最低條件：migration 存在、兩張新表啟用 RLS、公開角色無權限、RPC 權限正確、六個 Cron 各只有一筆、尖峰排程數不超過 8、佇列無重複或租約異常，且公開日期只前進到完整的同日 Base 結果。

## 2. Migration 是否已套用

```sql
select version
from supabase_migrations.schema_migrations
where version = '20260716101225';
```

預期：正好一列。若為零列，停止後續部署；不要手動偽造 migration history。

## 3. 資料表、RLS 與 Grants

### 3.1 表與 RLS

```sql
select
  c.relname as table_name,
  c.relrowsecurity as rls_enabled
from pg_catalog.pg_class c
join pg_catalog.pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public'
  and c.relkind = 'r'
  and c.relname in ('stock_lending_history', 'stock_enrichment_queue')
order by c.relname;
```

預期：兩列，且 `rls_enabled` 全部為 `true`。

### 3.2 公開角色不可存取、service role 只有必要 CRUD

```sql
with targets(table_name) as (
  values ('stock_lending_history'), ('stock_enrichment_queue')
), roles(role_name) as (
  values ('anon'), ('authenticated'), ('service_role')
)
select
  t.table_name,
  r.role_name,
  pg_catalog.has_table_privilege(
    r.role_name,
    format('public.%I', t.table_name),
    'SELECT'
  )
  and pg_catalog.has_table_privilege(r.role_name, format('public.%I', t.table_name), 'INSERT')
  and pg_catalog.has_table_privilege(r.role_name, format('public.%I', t.table_name), 'UPDATE')
  and pg_catalog.has_table_privilege(r.role_name, format('public.%I', t.table_name), 'DELETE')
    as has_crud
from targets t
cross join roles r
order by t.table_name, r.role_name;
```

預期：`anon`、`authenticated` 均為 `false`；`service_role` 為 `true`。

再確認沒有意外的公開 grant：

```sql
select table_name, grantee, privilege_type
from information_schema.role_table_grants
where table_schema = 'public'
  and table_name in ('stock_lending_history', 'stock_enrichment_queue')
  and grantee in ('PUBLIC', 'anon', 'authenticated')
order by table_name, grantee, privilege_type;
```

預期：零列。表擁有者的隱含權限不視為公開權限。

佇列 identity sequence 也必須保持 service-only：

```sql
select
  pg_catalog.has_sequence_privilege('anon', 'public.stock_enrichment_queue_id_seq', 'USAGE') as anon_usage,
  pg_catalog.has_sequence_privilege('authenticated', 'public.stock_enrichment_queue_id_seq', 'USAGE') as authenticated_usage,
  pg_catalog.has_sequence_privilege('service_role', 'public.stock_enrichment_queue_id_seq', 'USAGE') as service_usage;
```

預期：`false`、`false`、`true`。

## 4. RPC 存在性與執行權限

### 4.1 函式簽章

```sql
with expected(signature) as (
  values
    ('public.twss_claim_sync_lease(text,text,integer)'),
    ('public.twss_claim_enrichment_batch(text,integer,integer,text[])'),
    ('public.twss_complete_enrichment(bigint,text,date,jsonb)'),
    ('public.twss_fail_enrichment(bigint,text,text,text,integer)'),
    ('public.twss_release_enrichment(bigint[],text,integer)'),
    ('public.twss_analysis_inputs(text[],integer,integer,integer,integer)'),
    ('public.twss_enrichment_summary(date)'),
    ('public.twss_admin_operations_log_v200(integer)'),
    ('public.twss_admin_operations_log(integer)')
)
select
  signature,
  pg_catalog.to_regprocedure(signature) is not null as exists
from expected
order by signature;
```

預期：全部 `exists = true`。

### 4.2 權限矩陣

```sql
with expected(signature, authenticated_allowed) as (
  values
    ('public.twss_claim_sync_lease(text,text,integer)', false),
    ('public.twss_claim_enrichment_batch(text,integer,integer,text[])', false),
    ('public.twss_complete_enrichment(bigint,text,date,jsonb)', false),
    ('public.twss_fail_enrichment(bigint,text,text,text,integer)', false),
    ('public.twss_release_enrichment(bigint[],text,integer)', false),
    ('public.twss_analysis_inputs(text[],integer,integer,integer,integer)', false),
    ('public.twss_enrichment_summary(date)', false),
    ('public.twss_admin_operations_log_v200(integer)', false),
    ('public.twss_admin_operations_log(integer)', true)
)
select
  signature,
  pg_catalog.has_function_privilege('anon', signature, 'EXECUTE') as anon_execute,
  pg_catalog.has_function_privilege('authenticated', signature, 'EXECUTE') as authenticated_execute,
  pg_catalog.has_function_privilege('service_role', signature, 'EXECUTE') as service_execute,
  authenticated_allowed
from expected
order by signature;
```

預期：`anon_execute` 全為 `false`、`service_execute` 全為 `true`；只有 `twss_admin_operations_log(integer)` 的 `authenticated_execute` 為 `true`。該管理員 RPC 仍會在函式內驗證目前登入者是否為有效管理員，一般 authenticated 使用者呼叫時應得到 `admin_required`。

## 5. Cron 唯一性、排程與尖峰併發

### 5.1 六個新排程必須各有且只有一筆

```sql
with expected(jobname, expected_schedule) as (
  values
    ('twss-deep-listed', '*/2 7-15 * * 1-5'),
    ('twss-deep-otc', '*/2 7-15 * * 1-5'),
    ('twss-deep-etf', '*/2 7-15 * * 1-5'),
    ('twss-enrichment-weekday', '1,5,11,15,21,25,31,35,41,45,51,55 7-15 * * 1-5'),
    ('twss-v20-model-weekday', '*/2 7-15 * * 1-5'),
    ('twss-v20-model-weekday-final', '59 15 * * 1-5')
)
select
  e.jobname,
  count(j.jobid) as row_count,
  min(j.schedule) as actual_schedule,
  coalesce(bool_and(j.active), false) as all_active,
  count(j.jobid) = 1
    and min(j.schedule) = e.expected_schedule
    and coalesce(bool_and(j.active), false) as valid
from expected e
left join cron.job j on j.jobname = e.jobname
group by e.jobname, e.expected_schedule
order by e.jobname;
```

預期：六列均為 `row_count = 1`、`all_active = true`、`valid = true`。所有時間均為 UTC；`07:00–15:59 UTC` 對應台北 `15:00–23:59`。

### 5.2 設計尖峰驗算

下列查詢按目前已知 Cron 組合模擬一個平日。它只在上一節的實際 schedule 全部吻合時有效。

```sql
with minute_grid as (
  select h as utc_hour, m as utc_minute
  from generate_series(0, 23) h
  cross join generate_series(0, 59) m
), starts as (
  select
    utc_hour,
    utc_minute,
    (case when utc_hour between 0 and 15 and utc_minute % 10 = 0 then 1 else 0 end) +
    (case when utc_minute % 5 = 0 then 1 else 0 end) +
    (case when utc_hour between 7 and 15 and utc_minute % 2 = 0 then 4 else 0 end) +
    (case when utc_hour between 7 and 15 and utc_minute in (1,5,11,15,21,25,31,35,41,45,51,55) then 1 else 0 end) +
    (case when utc_hour = 15 and utc_minute = 59 then 1 else 0 end) +
    (case when utc_hour = 6 and utc_minute = 43 then 1 else 0 end) +
    (case when utc_hour in (9,13) and utc_minute = 10 then 1 else 0 end) +
    (case when utc_hour = 7 and utc_minute in (30,40) then 1 else 0 end) +
    (case when utc_hour = 10 and utc_minute = 20 then 1 else 0 end)
      as concurrent_starts
  from minute_grid
), peak as (
  select max(concurrent_starts) as peak_starts from starts
)
select
  p.peak_starts,
  array_agg(
    lpad(s.utc_hour::text, 2, '0') || ':' || lpad(s.utc_minute::text, 2, '0')
    order by s.utc_hour, s.utc_minute
  ) as peak_utc_minutes,
  p.peak_starts <= 8 as within_limit
from starts s
cross join peak p
where s.concurrent_starts = p.peak_starts
group by p.peak_starts;
```

預期：`peak_starts = 7`、`within_limit = true`。若日後新增或修改 Cron，必須先更新這個模型再上線；不要只看新六個工作而忽略既有 v19 與維護排程。

## 6. Enrichment 佇列與租約

### 6.1 唯一鍵與狀態一致性

```sql
select symbol, data_date, dataset_key, count(*) as duplicates
from public.stock_enrichment_queue
group by symbol, data_date, dataset_key
having count(*) > 1;
```

預期：零列。

```sql
select id, symbol, data_date, dataset_key, status
from public.stock_enrichment_queue
where (status = 'running' and (lease_owner is null or lease_until is null))
   or (status <> 'running' and (lease_owner is not null or lease_until is not null));
```

預期：零列。

### 6.2 最新交易日的佇列摘要

```sql
with current_cycle as (
  select cycle_date
  from public.stock_sync_state
  where job_key = 'universe'
)
select
  cycle_date,
  public.twss_enrichment_summary(cycle_date) as enrichment_summary
from current_cycle;
```

預期：一列。`unresolved` 可在背景補齊期間大於零，不能阻擋 Base 發布；排程結束後應逐步下降。`terminalErrors` 必須由管理員處理，但單一資料源錯誤不得讓首頁或 Base 分析失效。

需要展開追查時：

```sql
with current_cycle as (
  select cycle_date
  from public.stock_sync_state
  where job_key = 'universe'
)
select q.dataset_key, q.status, count(*) as rows
from public.stock_enrichment_queue q
join current_cycle c on c.cycle_date = q.data_date
group by q.dataset_key, q.status
order by q.dataset_key, q.status;
```

### 6.3 過期租約與 420 秒保護

```sql
select id, symbol, dataset_key, lease_until
from public.stock_enrichment_queue
where status = 'running'
  and lease_until < clock_timestamp()
order by lease_until;
```

預期：正常巡檢時為零列；Worker 剛中斷時可能短暫出現，下一次 claim 應自動接手。若連續兩個排程週期仍存在，檢查 Edge Function 日誌與 Cron 執行紀錄，不要直接刪列。

```sql
select
  position(
    '420' in pg_catalog.pg_get_functiondef(
      'public.twss_claim_sync_lease(text,text,integer)'::regprocedure
    )
  ) > 0 as sync_lease_guard_present,
  position(
    '420' in pg_catalog.pg_get_functiondef(
      'public.twss_claim_enrichment_batch(text,integer,integer,text[])'::regprocedure
    )
  ) > 0 as enrichment_lease_guard_present;
```

預期：兩欄均為 `true`。Base/模型與 Enrichment 的最短租約為 420 秒，成功時由 Worker 提前釋放，避免兩分鐘排程造成重複處理。

## 7. 同日 Base 與公開狀態

### 7.1 來源、模型與公開指標必須同日

```sql
with target as (
  select cycle_date as target_date
  from public.stock_sync_state
  where job_key = 'universe'
), base as (
  select
    count(*) as group_count,
    coalesce(bool_and(
      s.cycle_date = t.target_date
      and s.status in ('success', 'partial')
      and s.total_items > 0
      and s.processed_count >= s.total_items
      and split_part(coalesce(s.details ->> 'completedCycleKey', ''), ':', 1) = t.target_date::text
    ), false) as ready
  from public.stock_sync_state s
  cross join target t
  where s.job_key in ('deep_listed', 'deep_otc', 'deep_etf')
), model as (
  select s.*
  from public.stock_sync_state s
  where s.job_key = 'v20_model'
)
select
  t.target_date,
  b.group_count = 3 and b.ready as base_ready,
  m.status as model_status,
  m.details ->> 'publicationPhase' as publication_phase,
  m.details ->> 'publishedDataDate' as published_data_date,
  m.details ->> 'baseCompletedAt' as base_completed_at,
  m.details ->> 'enrichmentCompletedAt' as enrichment_completed_at,
  m.details ->> 'enrichmentPending' as enrichment_pending,
  m.details ->> 'dataCompleteness' as data_completeness,
  b.group_count = 3
    and b.ready
    and m.details ->> 'publishedDataDate' = t.target_date::text
    and m.details -> 'sourceDates' ->> 'universe' = t.target_date::text
    and m.details -> 'sourceDates' ->> 'listed' = t.target_date::text
    and m.details -> 'sourceDates' ->> 'otc' = t.target_date::text
    and m.details -> 'sourceDates' ->> 'etf' = t.target_date::text
    and m.details ->> 'publicationPhase' in ('base_ready', 'enriching', 'complete')
      as same_day_published
from target t
cross join base b
cross join model m;
```

判讀：

- Base 尚未完成：`base_ready = false`，公開指標必須保留上一個完整日期，不得提前切換。
- Base 已完成且排行榜交易成功：`same_day_published = true`。
- `publication_phase = base_ready` 或 `enriching`：同日 Base 已可用，FinMind 等補充資料仍在背景補齊，屬正常狀態。
- `publication_phase = complete`：Base 與可用的 Enrichment 已完成。
- Base 已完成但 `same_day_published = false`：停止前端切換並檢查 `v20_model` 的 `last_error`、retry queue 與排行榜刷新結果。

### 7.2 排行榜快照不可落後公開日期

```sql
with model as (
  select details ->> 'publishedDataDate' as published_date
  from public.stock_sync_state
  where job_key = 'v20_model'
)
select
  m.published_date,
  max(r.ranking_date)::text as latest_ranking_date,
  max(r.ranking_date)::text = m.published_date as ranking_matches_publication
from model m
left join public.v20_ranking_snapshots r
  on r.model_version = '20.0'
group by m.published_date;
```

預期：公開指標存在時 `ranking_matches_publication = true`。首頁、短期、中期、個股與 AI 每日報告都必須使用同一 `publishedDataDate`，不得混用尚未完成的較新資料。

## 8. 回滾方式

### 8.1 建議回滾：程式回退、資料庫保持向後相容

1. 先將 Vercel 與兩個 Edge Functions 回退至上一個已驗證版本。
2. 建立新的補償 migration：`supabase migration new rollback_db_first_pipeline`。不要刪除既有 migration history，也不要重跑整份舊 migration。
3. 在補償 migration 中以 job name 取消 `twss-enrichment-weekday` 與 `twss-v20-model-weekday-final`。
4. 僅複製舊 migration 的 Cron schedule 區塊，恢復：
   - `20260714134000_ultimate_speed_and_data_repairs.sql`：三個 deep job。
   - `20260716031500_harden_v20_public_read_model.sql`：原 `twss-v20-model-weekday`。
5. 套用補償 migration，再執行第 5 節的唯一性檢查。

舊排程基準為：deep listed `1,21,41 * * * *`、deep otc `8,28,48 * * * *`、deep ETF `15,35,55 * * * *`，v20 model `*/5 7-13 * * 1-5`。排程 body 應直接取自上述已提交 migration，避免手動重打 URL、header 或 Vault 參照。

### 8.2 資料庫物件處置

- 預設保留兩張新表、資料、索引與 RPC；它們是 service-only 且舊版不會呼叫，保留可避免資料遺失，也便於重新上線。
- 保留擴充後的 `twss_admin_operations_log(integer)` 是向後相容的；舊欄位仍在，新增欄位不會破壞舊管理後台。
- 只有在連同 v20 Worker 一起長期回退時，才於新的補償 migration 恢復 `20260714134500_sync_leases_retry_retention.sql` 中的舊 `twss_claim_sync_lease` 定義。
- 不要在緊急回滾中 `drop table ... cascade`、搬移兩個 Supabase 專案間的資料、交換兩專案用途或清除 queue audit rows。

### 8.3 回滾後驗證

回滾後確認：舊 API 路徑可用、登入與管理員權限正常、兩個 Supabase 專案仍維持原分工、Cron 沒有重複列、既有資料未減少，且公開日期仍指向最後一個完整排行榜快照。任何 DB 物件清理都應在觀察期後另開 migration 與備份，不與緊急回滾混在同一批執行。
