import assert from 'node:assert/strict';
import { readFile, readdir } from 'node:fs/promises';

const root = new URL('../', import.meta.url);
const [v20, index, styles, migrations] = await Promise.all([
  readFile(new URL('public/v20.js', root), 'utf8'),
  readFile(new URL('public/index.html', root), 'utf8'),
  readFile(new URL('public/styles.css', root), 'utf8'),
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
for (const label of ['自選', '持股', '提醒']) assert.ok(v20.includes(`>${label}</button>`), `missing 我的/${label} tab`);
assert.match(v20, /portfolio_positions\?user_id=eq\.\$\{encodeURIComponent\(owner\)\}&select=/);
assert.ok((v20.match(/user_id=eq\.\$\{encodeURIComponent\(owner\)\}/g) || []).length >= 3, 'select, patch and delete must filter by owner');
assert.match(v20, /on_conflict=user_id,symbol/);
assert.match(v20, /method: 'PATCH'/);
assert.match(v20, /method: 'DELETE'/);
assert.match(v20, /登入後使用目前持股/);
assert.match(v20, /未實現損益/);
assert.match(v20, /行情待補/);
assert.match(v20, /只保存目前股數與平均成本，不建立交易明細/);
assert.match(styles, /\.v20-mine-tabs/);
assert.match(styles, /\.v20-portfolio-metrics/);

console.log('portfolio center test passed');
