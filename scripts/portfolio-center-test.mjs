import assert from 'node:assert/strict';
import { readFile, readdir } from 'node:fs/promises';

const root = new URL('../', import.meta.url);
const [v20, index, styles, app, smart, migrations] = await Promise.all([
  readFile(new URL('public/v20.js', root), 'utf8'),
  readFile(new URL('public/index.html', root), 'utf8'),
  readFile(new URL('public/styles.css', root), 'utf8'),
  readFile(new URL('public/app.js', root), 'utf8'),
  readFile(new URL('public/smart.js', root), 'utf8'),
  readdir(new URL('supabase/migrations/', root)),
]);

const migrationName = migrations.find(name => name.endsWith('_add_portfolio_positions.sql'));
assert.ok(migrationName, 'portfolio migration must exist');
const sql = await readFile(new URL(`supabase/migrations/${migrationName}`, root), 'utf8');

assert.match(sql, /create table public\.portfolio_positions/i);
assert.match(sql, /id uuid primary key default extensions\.gen_random_uuid\(\)/i);
assert.match(sql, /user_id uuid not null references auth\.users\(id\) on delete cascade/i);
assert.match(sql, /symbol ~ '\^\[0-9A-Z\]\{2,12\}\$'/i);
assert.match(sql, /quantity numeric\([^)]*\) not null/i);
assert.match(sql, /check \(quantity > 0\)/i);
assert.match(sql, /check \(average_cost > 0\)/i);
assert.match(sql, /char_length\(note\) <= 1000/i);
assert.match(sql, /unique \(user_id, symbol\)/i);
assert.match(sql, /enable row level security/i);

for (const operation of ['select', 'insert', 'update', 'delete']) {
  assert.match(sql, new RegExp(`for ${operation} to authenticated`, 'i'), `missing ${operation} owner policy`);
}
assert.ok((sql.match(/\(select auth\.uid\(\)\) = user_id/gi) || []).length >= 5, 'RLS policies must enforce row ownership');
assert.match(sql, /revoke all on table public\.portfolio_positions from public, anon, authenticated/i);
assert.match(sql, /grant select, insert, update, delete on table public\.portfolio_positions to authenticated/i);
assert.match(sql, /grant all on table public\.portfolio_positions to service_role/i);
assert.match(sql, /create trigger portfolio_positions_set_updated_at/i);
assert.match(sql, /execute function public\.set_updated_at\(\)/i);

assert.match(index, /data-tab="watchlist"[^>]*>[\s\S]*?我的<\/button>/);
assert.match(v20, /pageHero\('WATCHLIST', '我的自選'/);
assert.match(v20, /只保存關注股票/);
assert.match(v20, /不記錄持股成本、損益或交易/);
assert.doesNotMatch(v20, /portfolio_positions/i,
  'portfolio data remains in CORE but must not be read or mutated by the public UI');
assert.doesNotMatch(v20, /data-portfolio-(?:edit|delete)/i);
assert.doesNotMatch(v20, /v20Portfolio(?:Quantity|Cost|Form)/);
assert.doesNotMatch(v20, /未實現損益|平均成本|新增目前持股|修改目前持股/);
assert.doesNotMatch(v20, /data-v20-mine="(?:portfolio|reminders)"/);
assert.match(styles, /\.v20-watch-metrics/);
assert.match(app, /if\(document\.querySelector\('script\[src\^="\/v20\.js"\]'\)\)S\.fundStatus='deferred';\s*else loadStocks\(\)/,
  'v20 boot must not download the legacy all-market stock payload');
assert.match(smart, /if \(!document\.querySelector\('script\[src\^="\/v20\.js"\]'\)\) loadSnapshot\(\)/,
  'v20 boot must not preload the legacy backend ranking snapshot');
assert.doesNotMatch(smart, /refresh=1|loadSnapshot\(true\)/);

console.log('watchlist-only product boundary test passed');
