(() => {
  'use strict';

  const SUPABASE_URL = 'https://lfkdkdyaatdlizryiyon.supabase.co';
  const SUPABASE_KEY = 'sb_publishable_r3h9eQIYdIqScvmc77avAg_OLgBT6lh';
  const SESSION_KEY = 'twss-market-admin-session-v18';
  const ADMIN_EMAIL_DOMAIN = 'admin.twss.local';
  const app = document.querySelector('#adminApp');
  const statusNode = document.querySelector('#adminStatus');
  const badgeNode = document.querySelector('#adminBadge');

  const state = {
    session: null,
    payload: null,
    filters: { group: 'all', status: 'all', query: '' }
  };

  const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, character => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  })[character]);
  const finite = value => value != null && Number.isFinite(Number(value)) ? Number(value) : null;
  const number = (value, digits = 0) => finite(value) == null ? '—' : Number(value).toLocaleString('zh-TW', { maximumFractionDigits: digits });
  const percent = value => finite(value) == null ? 0 : Math.max(0, Math.min(100, Number(value)));
  const rows = value => Array.isArray(value) ? value : value && typeof value === 'object'
    ? Object.entries(value).map(([key, item]) => ({ key, ...(item && typeof item === 'object' ? item : { value: item }) }))
    : [];
  const readSession = () => {
    try { return JSON.parse(localStorage.getItem(SESSION_KEY) || 'null'); } catch { return null; }
  };
  const saveSession = session => {
    state.session = session;
    if (session) localStorage.setItem(SESSION_KEY, JSON.stringify(session));
    else localStorage.removeItem(SESSION_KEY);
  };
  const timestamp = value => {
    if (!value) return '—';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return new Intl.DateTimeFormat('zh-TW', {
      timeZone: 'Asia/Taipei', year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false
    }).format(date);
  };
  const groupLabel = value => ({ listed: '上市', otc: '上櫃', etf: 'ETF' })[value] || value || '全市場';
  const jobLabel = value => ({
    universe: '全市場盤後資料',
    deep_listed: '上市深度分析',
    deep_otc: '上櫃深度分析',
    deep_etf: 'ETF 深度分析',
    v19_rankings: 'v19 排行榜快照',
    v19_news: '新聞與公告同步'
  })[value] || value || '未命名工作';
  const statusLabel = value => ({
    success: '完成', ready: '完成', final: '完成', healthy: '正常', running: '執行中',
    pending: '等待中', partial: '部分完成', building: '建立中', error: '錯誤', failed: '失敗'
  })[value] || value || '未知';
  const statusClass = value => ['success', 'ready', 'final', 'healthy'].includes(String(value))
    ? 'ok' : ['error', 'failed', 'critical'].includes(String(value)) ? 'bad' : '';
  const datasetLabels = {
    price: '每日行情', price_history: '歷史日線', monthly_revenue: '月營收', quarterly_revenue: '季度營收',
    quarterly_financials: '季度財報', income: '損益表', balance: '資產負債表', cashflow: '現金流量表',
    cash_conversion: '盈餘現金轉換', institutional: '法人籌碼', margin: '融資融券', lending: '借券',
    holdings: '集保持股', benchmark: '市場基準歷史', profile: 'ETF 基本資料', etf_profile: 'ETF 基本資料',
    premium_discount: 'ETF 折溢價', etf_premium_discount: 'ETF 折溢價', tracking_error: 'ETF 追蹤誤差',
    etf_tracking_error: 'ETF 追蹤誤差', fees: 'ETF 費用', etf_fees: 'ETF 費用', concentration: 'ETF 集中度',
    etf_top10_concentration: 'ETF 前十大集中度', deep_refresh: '深度資料更新', deep_analysis: '深度分析'
  };
  const classificationLabels = {
    scheduled_repair: '可補，已排程修復', upstream_error: 'API／來源暫時異常', stale_source: '等待官方更新期別',
    unavailable_from_source: '公開來源沒有歷史', official_not_provided: '免費官方來源未提供',
    insufficient_history: '歷史筆數尚未達門檻', not_applicable: '不適用', partial_source: '來源僅提供部分欄位'
  };
  const errorLabels = {
    rate_limited: 'API 額度暫滿', upstream_timeout: '上游回應逾時', upstream_5xx: '上游服務暫時異常',
    sync_error: '同步工作錯誤', upstream_authentication_failed: '上游驗證失敗', empty_response: '來源回傳空資料'
  };

  async function request(path, options = {}) {
    const headers = { apikey: SUPABASE_KEY, 'Content-Type': 'application/json', ...(options.headers || {}) };
    if (options.auth !== false && state.session?.access_token) headers.Authorization = `Bearer ${state.session.access_token}`;
    const response = await fetch(SUPABASE_URL + path, {
      method: options.method || 'GET', headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      cache: 'no-store'
    });
    let payload = null;
    try { payload = await response.json(); } catch { /* empty response */ }
    if (!response.ok) {
      const error = new Error(payload?.message || payload?.error_description || payload?.error || `HTTP ${response.status}`);
      error.status = response.status;
      error.code = payload?.code;
      throw error;
    }
    return payload;
  }

  async function refreshSession() {
    if (!state.session) return false;
    if ((state.session.expires_at || 0) > Date.now() / 1000 + 90) return true;
    if (!state.session.refresh_token) { saveSession(null); return false; }
    try {
      const session = await request('/auth/v1/token?grant_type=refresh_token', {
        method: 'POST', body: { refresh_token: state.session.refresh_token }, auth: false
      });
      session.expires_at = Math.floor(Date.now() / 1000) + (session.expires_in || 3600);
      saveSession(session);
      return true;
    } catch {
      saveSession(null);
      return false;
    }
  }

  function accountEmail(account) {
    const value = String(account || '').trim();
    if (value.includes('@')) return value.toLowerCase();
    if (!/^[A-Za-z0-9_.-]{3,32}$/.test(value)) return null;
    return `${value.toLowerCase()}@${ADMIN_EMAIL_DOMAIN}`;
  }

  async function signIn(account, password) {
    const email = accountEmail(account);
    if (!email) throw new Error('帳號格式不正確。');
    if (password.length < 6) throw new Error('管理員密碼至少需要 6 個字元。');
    const session = await request('/auth/v1/token?grant_type=password', {
      method: 'POST', body: { email, password }, auth: false
    });
    session.expires_at = Math.floor(Date.now() / 1000) + (session.expires_in || 3600);
    saveSession(session);
  }

  async function isAdmin() {
    if (!await refreshSession()) return false;
    return await request('/rest/v1/rpc/twss_is_admin', { method: 'POST', body: {} }) === true;
  }

  function setHeader(label, kind = '') {
    statusNode.textContent = label;
    badgeNode.className = `status-pill ${kind}`.trim();
    badgeNode.textContent = kind === 'ok' ? '管理員' : kind === 'bad' ? '拒絕存取' : '權限檢查中';
  }

  function renderLogin(message = '') {
    setHeader('請使用管理員帳號登入');
    app.innerHTML = `<section class="admin-login-card card accent">
      <h2>管理員登入</h2>
      <p class="muted">後台日誌包含同步工作、API 額度、修復佇列與錯誤時間軸，不開放一般帳戶查看。</p>
      <label>管理員帳號<input id="adminUsername" autocomplete="username" value="Migao" spellcheck="false"></label>
      <label>管理員密碼<input id="adminPassword" type="password" autocomplete="current-password" placeholder="輸入建立管理員時設定的密碼"></label>
      <button id="adminLogin" class="btn admin-main-action" type="button">登入後台</button>
      <div id="adminAuthMsg" class="muted admin-auth-message">${escapeHtml(message)}</div>
      <div class="notice"><b>安全說明</b><br>帳號預設為 Migao；密碼只保存在 Supabase Auth，不會寫入 GitHub、HTML 或 JavaScript。</div>
    </section>`;
    document.querySelector('#adminLogin').addEventListener('click', submitLogin);
    document.querySelector('#adminPassword').addEventListener('keydown', event => { if (event.key === 'Enter') submitLogin(); });
    requestAnimationFrame(() => document.querySelector('#adminPassword')?.focus());
  }

  async function submitLogin() {
    const button = document.querySelector('#adminLogin');
    const message = document.querySelector('#adminAuthMsg');
    button.disabled = true;
    button.textContent = '登入中…';
    message.textContent = '';
    try {
      await signIn(document.querySelector('#adminUsername').value, document.querySelector('#adminPassword').value);
      if (!await isAdmin()) {
        await logout(false);
        renderLogin('此帳戶沒有管理員權限。');
        return;
      }
      await loadConsole();
    } catch (error) {
      message.textContent = error.message === 'Invalid login credentials' ? '帳號或密碼不正確。' : error.message;
      button.disabled = false;
      button.textContent = '登入後台';
    }
  }

  async function logout(render = true) {
    try { if (state.session) await request('/auth/v1/logout', { method: 'POST', body: {} }); } catch { /* local logout still applies */ }
    saveSession(null);
    state.payload = null;
    if (render) renderLogin('已安全登出。');
  }

  function metric(label, value, note = '') {
    return `<div class="metric"><small>${escapeHtml(label)}</small><b>${escapeHtml(value)}</b>${note ? `<em>${escapeHtml(note)}</em>` : ''}</div>`;
  }

  function sourceCard(source, index) {
    const label = source.label || source.name || source.key || `資料來源 ${index + 1}`;
    const status = String(source.status || 'partial').toLowerCase();
    const covered = finite(source.covered);
    const total = finite(source.total);
    const coverage = total ? percent(covered / total * 100) : null;
    const missing = finite(source.missing);
    return `<article class="health-source">
      <div class="head"><div><b>${escapeHtml(label)}</b><div class="muted">資料日期 ${escapeHtml(source.latest || source.dataDate || '尚未回傳')}</div></div><span class="status-pill ${statusClass(status)}">${escapeHtml(statusLabel(status))}</span></div>
      ${coverage == null ? `<div class="admin-count-line">已涵蓋 <b>${number(covered)} 筆${missing == null ? '' : ` · 缺 ${number(missing)}`}</b></div>` : `<div class="health-progress-label"><span>涵蓋率 ${number(covered)}／${number(total)}</span><b>${number(coverage, 1)}%</b></div><div class="progress"><span style="width:${coverage}%"></span></div>`}
      <div class="muted small">${escapeHtml(source.reason || '沒有回報缺漏原因')}</div>
    </article>`;
  }

  function jobCard(job) {
    const progress = percent(job.progress);
    const error = job.lastErrorCode ? (errorLabels[job.lastErrorCode] || job.lastErrorCode) : '';
    return `<article class="admin-job card ${job.status === 'error' ? 'error-card' : job.status === 'success' ? 'accent' : ''}">
      <div class="head"><div><h3>${escapeHtml(jobLabel(job.jobKey))}</h3><div class="muted">${escapeHtml(groupLabel(job.group))} · 資料日 ${escapeHtml(job.cycleDate || '—')}</div></div><span class="status-pill ${statusClass(job.status)}">${escapeHtml(statusLabel(job.status))}</span></div>
      <div class="health-progress-label"><span>累積進度 ${number(job.processed)}／${number(job.total)}</span><b>${number(progress, 1)}%</b></div>
      <div class="progress"><span style="width:${progress}%"></span></div>
      <div class="admin-job-meta"><span>游標 ${number(job.cursor)}</span><span>最後股票 ${escapeHtml(job.lastSymbol || '—')}</span><span>更新 ${escapeHtml(timestamp(job.updatedAt))}</span><span>下次 ${escapeHtml(timestamp(job.nextRunAt))}</span></div>
      ${error ? `<div class="admin-error-line"><b>${escapeHtml(error)}</b><span>${escapeHtml(job.lastErrorPreview || '')}</span></div>` : ''}
    </article>`;
  }

  function repairItem(item) {
    const reasons = Array.isArray(item.repairReasons) ? item.repairReasons : [];
    const label = item.errorKind ? (errorLabels[item.errorKind] || item.errorKind) : reasons.join('、') || '等待後端判定';
    return `<article class="admin-log-row" data-group="${escapeHtml(item.group || '')}" data-status="${escapeHtml(item.status || '')}">
      <div><b>${escapeHtml(item.name || item.symbol || '未命名')} ${escapeHtml(item.symbol || '')}</b><div class="muted">${escapeHtml(groupLabel(item.group))} · 資料日 ${escapeHtml(item.dataDate || '—')}</div></div>
      <div class="admin-log-reason"><span class="tag ${item.status === 'error' ? 'bad' : 'warn'}">${escapeHtml(item.status === 'error' ? '錯誤' : '待修復')}</span><b>${escapeHtml(label)}</b><small class="muted">嘗試 ${number(item.attemptCount)} 次 · 下次 ${escapeHtml(timestamp(item.nextRetryAt))}</small></div>
    </article>`;
  }

  function missingExample(item) {
    const dataset = datasetLabels[item.dataset] || item.dataset || '資料';
    const reason = item.reason || classificationLabels[item.classification] || item.classification || '等待後端判定';
    return `<article class="admin-log-row">
      <div><b>${escapeHtml(item.name || item.symbol || '未命名')} ${escapeHtml(item.symbol || '')}</b><div class="muted">${escapeHtml(groupLabel(item.group || item.market))} · ${escapeHtml(dataset)}</div></div>
      <div class="admin-log-reason"><span class="tag ${item.retryable ? 'warn' : 'info'}">${item.retryable ? '可重試' : '來源限制'}</span><b>${escapeHtml(reason)}</b></div>
    </article>`;
  }

  function timelineItem(item) {
    const labels = { sync_job: '同步工作', analysis_error: '分析錯誤', repair_pending: '待修復', api_quota: 'API 使用', ranking_cycle: '排行週期' };
    const severity = item.type === 'analysis_error' ? 'bad' : item.type === 'repair_pending' ? 'warn' : 'info';
    const detail = item.type === 'api_quota' ? `${number(item.units)} 單位`
      : item.type === 'ranking_cycle' ? `${number(item.scored)}／${number(item.expected)}`
      : statusLabel(item.status);
    return `<div class="admin-timeline-item"><span class="tag ${severity}">${escapeHtml(labels[item.type] || item.type)}</span><div><b>${escapeHtml(item.key || '—')}</b><div class="muted">${escapeHtml(groupLabel(item.group))} · ${escapeHtml(detail)}</div></div><time>${escapeHtml(timestamp(item.at))}</time></div>`;
  }

  function matchesFilters(item) {
    const group = String(item.group || '');
    const status = String(item.status || (item.needsRepair ? 'pending' : ''));
    const haystack = [item.symbol, item.name, item.errorKind, ...(item.repairReasons || [])].join(' ').toLowerCase();
    return (state.filters.group === 'all' || group === state.filters.group)
      && (state.filters.status === 'all' || status === state.filters.status || (state.filters.status === 'pending' && item.needsRepair))
      && (!state.filters.query || haystack.includes(state.filters.query.toLowerCase()));
  }

  function renderConsole() {
    const payload = state.payload || {};
    const summary = payload.summary || {};
    const health = payload.health || {};
    const jobs = rows(payload.jobs);
    const sources = rows(health.sources);
    const missingSummary = rows(payload.missingData?.summary);
    const missingExamples = rows(payload.missingData?.examples);
    const repairItems = rows(payload.repairQueue?.items).filter(matchesFilters);
    const cycles = rows(payload.rankingCycles);
    const timeline = rows(payload.timeline);
    const quota = payload.apiQuota || {};
    const groupQuota = rows(quota.byJob);
    const overall = String(health.overallStatus || '').toLowerCase();
    setHeader(`登入者 ${payload.admin?.username || '管理員'} · 更新 ${timestamp(payload.generatedAt)}`, 'ok');
    app.innerHTML = `<section class="admin-toolbar card">
      <div class="head"><div><h2>系統運作總覽</h2><div class="muted">只顯示去除權杖與敏感標頭後的日誌。</div></div><span class="status-pill ${statusClass(overall)}">${escapeHtml(statusLabel(overall))}</span></div>
      <div class="admin-action-grid"><button id="adminRefresh" class="btn" type="button">重新整理</button><button id="adminCopyReport" class="btn secondary" type="button">複製修復報告</button><button id="adminLogout" class="btn danger" type="button">登出</button></div>
    </section>
    <section class="admin-summary grid three">
      ${metric('待修復', `${number(summary.pendingRepairs)} 筆`)}
      ${metric('分析錯誤', `${number(summary.analysisErrors)} 筆`)}
      ${metric('失敗工作', `${number(summary.failedJobs)} 個`)}
      ${metric('執行中', `${number(summary.runningJobs)} 個`)}
      ${metric('完成分析', `${number(summary.readyAnalyses)} 檔`)}
      ${metric('最新資料日', summary.latestDataDate || health.dataDate || '—')}
    </section>
    <section class="health-section"><h2>同步工作</h2><div class="admin-job-list">${jobs.length ? jobs.map(jobCard).join('') : '<div class="card muted">尚無同步工作日誌。</div>'}</div></section>
    <section class="health-section"><h2>API 使用量</h2><div class="card"><div class="grid three">${metric('近 60 分鐘', `${number(quota.usedLast60Minutes)} 單位`)}${metric('預約紀錄', `${number(quota.reservationCount)} 筆`)}${metric('最早釋放', timestamp(quota.nextReleaseAt))}</div>${groupQuota.length ? `<div class="rules admin-quota-tags">${groupQuota.map(item => `<span>${escapeHtml(jobLabel(item.key))} ${number(item.value)} 單位</span>`).join('')}</div>` : ''}</div></section>
    <section class="health-section"><h2>資料來源</h2><div class="health-sources">${sources.length ? sources.map(sourceCard).join('') : '<div class="card muted">來源健康資料尚未回傳。</div>'}</div></section>
    <section class="health-section"><div class="head"><div><h2>修復佇列</h2><div class="muted">可直接篩選並複製成修復報告。</div></div><span class="status-pill">${number(payload.repairQueue?.pending)} pending · ${number(payload.repairQueue?.errors)} errors</span></div>
      <div class="card admin-filter-grid">
        <label>市場<select id="adminGroupFilter"><option value="all">全部市場</option><option value="listed">上市</option><option value="otc">上櫃</option><option value="etf">ETF</option></select></label>
        <label>狀態<select id="adminStatusFilter"><option value="all">全部狀態</option><option value="pending">待修復</option><option value="error">錯誤</option></select></label>
        <label>搜尋<input id="adminQueryFilter" value="${escapeHtml(state.filters.query)}" placeholder="股票代號、名稱或錯誤類型"></label>
      </div>
      ${missingSummary.length ? `<div class="rules health-classifications">${missingSummary.map(item => `<span>${escapeHtml(datasetLabels[item.dataset] || item.dataset || '資料')} · ${escapeHtml(classificationLabels[item.classification] || item.classification || '待判定')} ${number(item.count)} 筆</span>`).join('')}</div>` : ''}
      <div class="admin-log-list">${repairItems.length ? repairItems.map(repairItem).join('') : '<div class="card muted">目前篩選條件下沒有待修復項目。</div>'}</div>
      ${missingExamples.length ? `<details class="health-issues admin-details"><summary>查看來源缺漏範例（${number(missingExamples.length)}）</summary><div class="admin-log-list">${missingExamples.map(missingExample).join('')}</div></details>` : ''}
    </section>
    <section class="health-section"><h2>排行榜累積週期</h2><div class="admin-cycle-list">${cycles.length ? cycles.map(cycle => `<article class="admin-cycle"><div><b>${escapeHtml(groupLabel(cycle.group))} · ${escapeHtml(cycle.scoreDate || '—')}</b><div class="muted">模型 ${escapeHtml(cycle.modelVersion || '—')} · 更新 ${escapeHtml(timestamp(cycle.updatedAt))}</div></div><div><span class="status-pill ${statusClass(cycle.status)}">${escapeHtml(statusLabel(cycle.status))}</span><b>${number(cycle.scored)}／${number(cycle.expected)}</b></div></article>`).join('') : '<div class="card muted">排行榜週期尚未累積。</div>'}</div></section>
    <section class="health-section"><h2>最近事件時間軸</h2><div class="card admin-timeline">${timeline.length ? timeline.map(timelineItem).join('') : '<div class="muted">尚無事件。</div>'}</div></section>`;

    const groupFilter = document.querySelector('#adminGroupFilter');
    const statusFilter = document.querySelector('#adminStatusFilter');
    groupFilter.value = state.filters.group;
    statusFilter.value = state.filters.status;
    groupFilter.addEventListener('change', event => { state.filters.group = event.target.value; renderConsole(); });
    statusFilter.addEventListener('change', event => { state.filters.status = event.target.value; renderConsole(); });
    document.querySelector('#adminQueryFilter').addEventListener('change', event => { state.filters.query = event.target.value.trim(); renderConsole(); });
    document.querySelector('#adminQueryFilter').addEventListener('keydown', event => { if (event.key === 'Enter') { state.filters.query = event.target.value.trim(); renderConsole(); } });
    document.querySelector('#adminRefresh').addEventListener('click', loadConsole);
    document.querySelector('#adminCopyReport').addEventListener('click', copyReport);
    document.querySelector('#adminLogout').addEventListener('click', () => logout(true));
  }

  function reportText() {
    const payload = state.payload || {};
    const summary = payload.summary || {};
    const missing = rows(payload.missingData?.summary);
    const repairs = rows(payload.repairQueue?.items).filter(matchesFilters);
    const jobs = rows(payload.jobs);
    return [
      '台股智選 v18.0.0 管理後台修復報告',
      `產生時間：${timestamp(payload.generatedAt)}`,
      `資料日期：${summary.latestDataDate || payload.health?.dataDate || '—'}`,
      '',
      `摘要：待修復 ${number(summary.pendingRepairs)}、分析錯誤 ${number(summary.analysisErrors)}、失敗工作 ${number(summary.failedJobs)}、完成分析 ${number(summary.readyAnalyses)}`,
      '',
      '同步工作：',
      ...jobs.map(job => `- ${jobLabel(job.jobKey)}｜${statusLabel(job.status)}｜${number(job.processed)}/${number(job.total)} (${number(job.progress, 1)}%)｜資料日 ${job.cycleDate || '—'}${job.lastErrorCode ? `｜${errorLabels[job.lastErrorCode] || job.lastErrorCode}` : ''}`),
      '',
      '缺漏分類：',
      ...(missing.length ? missing.map(item => `- ${datasetLabels[item.dataset] || item.dataset || '資料'}｜${classificationLabels[item.classification] || item.classification || '待判定'}｜${number(item.count)} 筆`) : ['- 無']),
      '',
      `修復項目（目前篩選 ${repairs.length} 筆）：`,
      ...(repairs.length ? repairs.map(item => `- ${item.name || ''} ${item.symbol || ''}｜${groupLabel(item.group)}｜${item.status === 'error' ? '錯誤' : '待修復'}｜${item.errorKind || (item.repairReasons || []).join(',') || '待判定'}｜嘗試 ${number(item.attemptCount)} 次｜下次 ${timestamp(item.nextRetryAt)}`) : ['- 無'])
    ].join('\n');
  }

  async function copyReport() {
    const button = document.querySelector('#adminCopyReport');
    const original = button.textContent;
    try {
      const text = reportText();
      if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(text);
      else {
        const textarea = document.createElement('textarea');
        textarea.value = text; textarea.style.position = 'fixed'; textarea.style.opacity = '0';
        document.body.append(textarea); textarea.select(); document.execCommand('copy'); textarea.remove();
      }
      button.textContent = '已複製，可直接貼給我';
    } catch {
      button.textContent = '複製失敗，請再試一次';
    }
    setTimeout(() => { if (button.isConnected) button.textContent = original; }, 2200);
  }

  async function loadConsole() {
    const refresh = document.querySelector('#adminRefresh');
    if (refresh) { refresh.disabled = true; refresh.textContent = '整理日誌中…'; }
    setHeader('正在讀取管理員日誌…');
    try {
      if (!await isAdmin()) {
        await logout(false);
        renderLogin('管理員登入已失效，請重新登入。');
        return;
      }
      state.payload = await request('/rest/v1/rpc/twss_admin_operations_log', { method: 'POST', body: { p_limit: 80 } });
      renderConsole();
    } catch (error) {
      if (error.status === 401 || error.status === 403 || error.code === '42501') {
        await logout(false);
        renderLogin('沒有管理員權限，或登入已過期。');
        return;
      }
      setHeader('管理後台暫時無法載入', 'bad');
      app.innerHTML = `<div class="card error-card"><h2>日誌讀取失敗</h2><p class="muted">${escapeHtml(error.message)}</p><button id="adminRetry" class="btn admin-main-action" type="button">重新讀取</button></div>`;
      document.querySelector('#adminRetry').addEventListener('click', loadConsole);
    }
  }

  async function init() {
    state.session = readSession();
    if (!state.session || !await refreshSession()) { renderLogin(); return; }
    try {
      if (!await isAdmin()) { renderLogin('目前登入的是一般帳戶，請改用管理員帳號。'); return; }
      await loadConsole();
    } catch {
      renderLogin('管理員權限檢查暫時失敗，請重新登入。');
    }
  }

  init();
})();
