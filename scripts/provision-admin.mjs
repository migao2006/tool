const url = String(process.env.SUPABASE_URL || '').replace(/\/$/, '');
const serviceKey = String(process.env.SUPABASE_SERVICE_ROLE_KEY || '');
const username = String(process.env.TWSS_ADMIN_USERNAME || 'Migao').trim();
const password = String(process.env.TWSS_ADMIN_PASSWORD || '');
const email = String(process.env.TWSS_ADMIN_EMAIL || `${username.toLowerCase()}@admin.twss.local`).trim().toLowerCase();

if (!url || !serviceKey) {
  throw new Error('請先設定 SUPABASE_URL 與 SUPABASE_SERVICE_ROLE_KEY。');
}
if (!/^[A-Za-z0-9_.-]{3,32}$/.test(username)) {
  throw new Error('TWSS_ADMIN_USERNAME 必須是 3～32 個英數字、句點、底線或連字號。');
}
if (password.length < 6) {
  throw new Error('TWSS_ADMIN_PASSWORD 至少需要 6 個字元；Supabase Auth 不接受五字元密碼。');
}

const headers = {
  apikey: serviceKey,
  Authorization: `Bearer ${serviceKey}`,
  'Content-Type': 'application/json'
};

async function request(path, options = {}) {
  const response = await fetch(url + path, { ...options, headers: { ...headers, ...(options.headers || {}) } });
  let body = null;
  try { body = await response.json(); } catch { /* empty response */ }
  if (!response.ok) {
    const error = new Error(body?.message || body?.msg || body?.error || `HTTP ${response.status}`);
    error.status = response.status;
    error.body = body;
    throw error;
  }
  return body;
}

async function findExistingUser() {
  for (let page = 1; page <= 20; page += 1) {
    const result = await request(`/auth/v1/admin/users?page=${page}&per_page=100`);
    const users = Array.isArray(result?.users) ? result.users : [];
    const match = users.find(user => String(user.email || '').toLowerCase() === email);
    if (match) return match;
    if (users.length < 100) return null;
  }
  return null;
}

let user = await findExistingUser();
if (!user) {
  user = await request('/auth/v1/admin/users', {
    method: 'POST',
    body: JSON.stringify({
      email,
      password,
      email_confirm: true,
      app_metadata: { twss_admin_account: username }
    })
  });
} else {
  user = await request(`/auth/v1/admin/users/${encodeURIComponent(user.id)}`, {
    method: 'PUT',
    body: JSON.stringify({
      password,
      email_confirm: true,
      app_metadata: { ...(user.app_metadata || {}), twss_admin_account: username }
    })
  });
}

await request('/rest/v1/app_admins?on_conflict=user_id', {
  method: 'POST',
  headers: { Prefer: 'resolution=merge-duplicates,return=minimal' },
  body: JSON.stringify([{ user_id: user.id, username, active: true }])
});

console.log(`管理員已建立：${username} (${email})`);
console.log(`Auth user id：${user.id}`);
console.log('密碼未輸出；請妥善保管並定期更換。');
