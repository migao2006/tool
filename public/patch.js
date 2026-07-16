(() => {
  'use strict';
  const userData = globalThis.twssUserData;
  // Audited legacy paid-analysis builds: responses only lived in an in-memory
  // Map and the backend, so no legacy localStorage key is known. Keep the
  // cleanup allowlist explicit and empty rather than deleting guessed user data.
  const LEGACY_AI_LOCAL_STORAGE_KEYS = Object.freeze([]);
  for (const key of LEGACY_AI_LOCAL_STORAGE_KEYS) localStorage.removeItem(key);
  const patchState = { mineTab: 'watch' };
  const localRead = (key, fallback = []) => { try { return JSON.parse(localStorage.getItem(key) || JSON.stringify(fallback)); } catch { return fallback; } };
  const localWrite = (key, value) => localStorage.setItem(key, JSON.stringify(value));
  const getAlertStore = () => localRead(userData.storageKey('rule-alerts'), { events: [], lastSeen: {} });
  const setAlertStore = value => localWrite(userData.storageKey('rule-alerts'), value);
  const getCompareStore = () => {
    const stored = localRead(userData.storageKey('compare'), { group: null, symbols: [] });
    return {
      group: ['listed', 'otc', 'etf'].includes(stored?.group) ? stored.group : null,
      symbols: [...new Set(Array.isArray(stored?.symbols) ? stored.symbols.map(String) : [])].slice(0, 4)
    };
  };
  const setCompareStore = value => localWrite(userData.storageKey('compare'), value);
  const escapeText = value => String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
  const average = values => { const valid = values.filter(value => value != null && Number.isFinite(value)); return valid.length ? valid.reduce((sum, value) => sum + value, 0) / valid.length : null; };
  const median = values => { const valid = values.filter(value => value != null && Number.isFinite(value)).sort((a, b) => a - b); if (!valid.length) return null; const middle = Math.floor(valid.length / 2); return valid.length % 2 ? valid[middle] : (valid[middle - 1] + valid[middle]) / 2; };
  const groupLabel = value => ({ listed: '上市', otc: '上櫃', etf: 'ETF' })[value] || value;

  function ultimateRows() {
    const snapshot = globalThis.twssUltimateSnapshot?.();
    if (!snapshot?.groups) return [];
    return Object.entries(snapshot.groups).flatMap(([group, rows]) => (Array.isArray(rows) ? rows : []).map((row, index) => ({ ...row, group, rank: index + 1 })));
  }

  function comparisonRows() {
    const stored = getCompareStore();
    const deep = new Map(ultimateRows().map(row => [String(row.stock?.symbol || ''), row]));
    return stored.symbols.map(symbol => {
      const stock = S.stocks.find(item => String(item.symbol) === symbol);
      if (!stock) return null;
      const row = deep.get(symbol) || {};
      const group = row.group || instrumentGroup(stock);
      if (stored.group && group !== stored.group) return null;
      return { ...row, group, stock: { ...stock, ...(row.stock || {}) }, result: row.result || null, analysis: row.analysis || null };
    }).filter(Boolean);
  }

  function isCompared(symbol) {
    return getCompareStore().symbols.includes(String(symbol));
  }

  function toggleComparison(symbol) {
    const stock = S.stocks.find(item => String(item.symbol) === String(symbol));
    if (!stock) return;
    const group = instrumentGroup(stock);
    const stored = getCompareStore();
    const index = stored.symbols.indexOf(String(symbol));
    if (index >= 0) {
      stored.symbols.splice(index, 1);
      if (!stored.symbols.length) stored.group = null;
    } else {
      if (stored.symbols.length && stored.group !== group) {
        if (!confirm(`比較器目前是${groupLabel(stored.group)}組。要清除原比較並改成${groupLabel(group)}組嗎？`)) return;
        stored.symbols = [];
      }
      if (stored.symbols.length >= 4) {
        alert('同一組最多比較 4 檔，請先移除一檔。');
        return;
      }
      stored.group = group;
      stored.symbols.push(String(symbol));
    }
    setCompareStore(stored);
    syncCompareButtons();
    if (S.tab === 'mine' && patchState.mineTab === 'compare') render();
  }

  function syncCompareButtons() {
    qa('[data-compare]').forEach(button => {
      const active = isCompared(button.dataset.compare);
      button.classList.toggle('active', active);
      button.setAttribute('aria-pressed', String(active));
      button.textContent = active ? '✓ 已比較' : '＋比較';
    });
  }

  function csvCell(value) {
    let output = value == null ? '' : String(value);
    if (/^[=+\-@]/.test(output)) output = `'${output}`;
    return `"${output.replaceAll('"', '""')}"`;
  }

  function downloadCsv(filename, rows) {
    const csv = `\uFEFF${rows.map(row => row.map(csvCell).join(',')).join('\r\n')}`;
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = filename;
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }

  const finiteValue = value => value != null && Number.isFinite(Number(value)) ? Number(value) : null;
  const displayNumber = (value, digits = 1, suffix = '') => finiteValue(value) == null ? '—' : `${fmt(Number(value), digits)}${suffix}`;

  function comparisonRank(row) {
    const trend = row.result?.trend || row.trend || row.context?.trend || {};
    return trend.currentDate && String(row.dataDate || '') === String(trend.currentDate) && finiteValue(trend.rank) != null
      ? `第 ${fmt(trend.rank, 0)} 名`
      : '正式排名累積中';
  }

  function comparisonMetrics(group) {
    const common = [
      ['資料日期', row => row.dataDate || '—'],
      ['正式排名', row => comparisonRank(row)],
      ['最終分數', row => displayNumber(row.result?.score, 0, ' 分')],
      ['資料信心', row => displayNumber(row.result?.confidence, 0, '%')],
      ['候選狀態', row => row.result?.official ? '正式候選' : '驗證／信心未達標'],
      ['收盤價', row => displayNumber(row.stock?.close, 2)],
      ['風險扣分', row => displayNumber(row.result?.risk?.deduction, 0, ' 分')],
      ['資料缺漏', row => `${row.result?.missing?.length || 0} 項`]
    ];
    if (group === 'etf') return [...common,
      ['20 日動能', row => displayNumber(row.analysis?.price?.return20, 1, '%')],
      ['20 日相對市場', row => displayNumber(row.analysis?.price?.relative20, 1, '%')],
      ['5／20 日量能比', row => displayNumber(row.analysis?.price?.volumeRatio, 2, ' 倍')],
      ['ATR 波動', row => displayNumber(row.analysis?.price?.atrPct, 1, '%')],
      ['追蹤指數', row => row.analysis?.etf?.benchmark || '—'],
      ['折溢價', row => displayNumber(row.analysis?.etf?.premiumDiscount, 2, '%')],
      ['基金結構', row => row.analysis?.etf?.leveraged ? '槓桿型' : row.analysis?.etf?.inverse ? '反向型' : row.analysis?.etf?.fundType ? '一般型' : '—']
    ];
    return [...common,
      ['3 月平均營收年增', row => displayNumber(row.analysis?.revenue?.avg3Yoy, 1, '%')],
      ['營收加速度', row => displayNumber(row.analysis?.revenue?.acceleration3, 1, '%')],
      ['營業利益率', row => displayNumber(row.analysis?.financial?.operatingMargin, 1, '%')],
      ['現金轉換', row => displayNumber(row.analysis?.financial?.cashConversion, 2, ' 倍')],
      ['20 日法人買賣超', row => displayNumber(row.analysis?.institutional?.inst20, 0, ' 張')],
      ['近 5 日法人強度', row => displayNumber(row.analysis?.institutional?.intensity5, 1, '%')],
      ['20 日相對大盤', row => displayNumber(row.analysis?.price?.relative20, 1, '%')],
      ['5／20 日量能比', row => displayNumber(row.analysis?.price?.volumeRatio, 2, ' 倍')],
      ['本益比', row => finiteValue(row.stock?.pe) > 0 ? displayNumber(row.stock.pe, 2, ' 倍') : '—'],
      ['股價淨值比', row => displayNumber(row.stock?.pb, 2, ' 倍')]
    ];
  }

  function exportComparison() {
    const rows = comparisonRows();
    if (!rows.length) return;
    const metrics = comparisonMetrics(rows[0].group);
    downloadCsv(`台股智選-${groupLabel(rows[0].group)}比較-${S.date || today()}.csv`, [
      ['指標', ...rows.map(row => `${row.stock.name} ${row.stock.symbol}`)],
      ...metrics.map(([label, reader]) => [label, ...rows.map(reader)])
    ]);
  }

  function exportGroupRanking(group) {
    const rows = ultimateRows().filter(row => row.group === group);
    if (!rows.length) {
      alert(`${groupLabel(group)}深度排行榜尚未載入，請先開啟機會選股頁。`);
      return;
    }
    const metrics = comparisonMetrics(group);
    downloadCsv(`台股智選-${groupLabel(group)}排行榜-${S.date || today()}.csv`, [
      ['組內順序', '股票代號', '股票名稱', '市場', '產業', ...metrics.map(([label]) => label)],
      ...rows.map((row, index) => [index + 1, row.stock?.symbol, row.stock?.name, groupLabel(group), row.stock?.industry || '', ...metrics.map(([, reader]) => reader(row))])
    ]);
  }

  function alertSnapshot(row) {
    const trend = row?.trend || row?.result?.trend || row?.context?.trend || {};
    const finalDate = trend.currentDate || null;
    if (!finalDate || String(row?.dataDate || '') !== String(finalDate)) return null;
    const technical = row?.analysis?.price || {};
    const revenue = row?.analysis?.revenue || {};
    const institutional = row?.analysis?.institutional || {};
    return {
      dataDate: finalDate,
      group: row.group,
      rank: Number.isFinite(Number(trend.rank)) ? Number(trend.rank) : null,
      score: Number.isFinite(Number(row.result?.score)) ? Number(row.result.score) : null,
      official: row.result?.official === true,
      revenueAcceleration: Number.isFinite(Number(revenue.acceleration3)) ? Number(revenue.acceleration3) : null,
      institutionalIntensity: Number.isFinite(Number(institutional.intensity5)) ? Number(institutional.intensity5) : null,
      breakout: technical.breakout20 === true || technical.breakout === true,
      overheat: Number(technical.distanceMa20) >= 12 || Number(technical.rsi14) >= 75,
      present: true
    };
  }

  function refreshRuleAlerts() {
    const watched = new Set(getWatchlist().map(item => item.symbol));
    const rowMap = new Map(ultimateRows().filter(row => watched.has(row.stock?.symbol) && alertSnapshot(row)).map(row => [row.stock.symbol, row]));
    if (!rowMap.size) return getAlertStore();
    const stored = getAlertStore();
    const events = Array.isArray(stored.events) ? stored.events : [];
    const lastSeen = stored.lastSeen && typeof stored.lastSeen === 'object' ? stored.lastSeen : {};
    const existing = new Set(events.map(event => event.key));
    const definitions = [];
    for (const [symbol, row] of rowMap) {
      const current = alertSnapshot(row);
      if (!current) continue;
      const previous = lastSeen[symbol];
      if (previous && previous.dataDate !== current.dataDate) {
        if ((previous.score ?? -Infinity) < 70 && (current.score ?? -Infinity) >= 70) definitions.push([symbol, row, current, 'score70', '機會分數突破 70', `分數由 ${previous.score ?? '—'} 升至 ${current.score}。`]);
        if (!previous.official && current.official) definitions.push([symbol, row, current, 'official', '進入正式候選', '資料信心與風險條件已達正式候選門檻。']);
        if ((previous.rank == null || previous.rank > 10) && current.rank <= 10) definitions.push([symbol, row, current, 'top10', `進入${groupLabel(current.group)}前 10 名`, `目前排名第 ${current.rank}。`]);
        if ((previous.revenueAcceleration ?? 0) <= 0 && (current.revenueAcceleration ?? 0) > 0) definitions.push([symbol, row, current, 'revenue', '營收加速度轉正', `最新營收加速度 ${fmt(current.revenueAcceleration, 1)}%。`]);
        if ((previous.institutionalIntensity ?? 0) <= 0 && (current.institutionalIntensity ?? 0) > 0) definitions.push([symbol, row, current, 'institution', '法人強度轉正', `近 5 日法人強度 ${fmt(current.institutionalIntensity, 1)}%。`]);
        if (!previous.breakout && current.breakout) definitions.push([symbol, row, current, 'breakout', '出現 20 日突破', '價量資料符合突破條件，仍需留意追價風險。']);
        if (!previous.overheat && current.overheat) definitions.push([symbol, row, current, 'overheat', '短線過熱警示', '股價與均線距離或 RSI 已進入過熱條件。']);
        if (previous.official && !current.official) definitions.push([symbol, row, current, 'lost', '正式候選資格失效', '最新資料已不符合正式候選門檻，請重新檢視原因。']);
      }
      lastSeen[symbol] = current;
    }
    for (const [symbol, row, current, type, title, message] of definitions) {
      const key = `${symbol}:${current.dataDate}:${type}:${current.score ?? ''}:${current.rank ?? ''}`;
      if (existing.has(key)) continue;
      existing.add(key);
      events.unshift({ key, symbol, name: row.stock?.name || symbol, group: current.group, dataDate: current.dataDate, type, title, message, read: false, createdAt: new Date().toISOString() });
    }
    const next = { events: events.slice(0, 200), lastSeen };
    setAlertStore(next);
    return next;
  }

  function marketEnvironment() {
    const tradable = S.stocks.filter(stock => stock.change != null);
    const up = tradable.filter(stock => stock.change > 0).length;
    const down = tradable.filter(stock => stock.change < 0).length;
    const flat = tradable.length - up - down;
    const avgChange = average(tradable.map(stock => stock.change)) || 0;
    const breadth = tradable.length ? up / tradable.length * 100 : 0;
    const foreign = S.stocks.reduce((sum, stock) => sum + (stock.foreign || 0), 0);
    const institutions = S.stocks.reduce((sum, stock) => sum + (stock.inst || 0), 0);
    const label = breadth >= 60 && avgChange > 0 ? '市場偏多' : breadth <= 40 && avgChange < 0 ? '市場偏空' : '市場震盪';
    const industries = [...new Set(S.stocks.map(stock => stock.industry).filter(Boolean))].map(industry => {
      const stocks = S.stocks.filter(stock => stock.industry === industry);
      const valid = stocks.filter(stock => stock.change != null);
      return {
        industry,
        count: stocks.length,
        avgChange: average(valid.map(stock => stock.change)) || 0,
        breadth: valid.length ? valid.filter(stock => stock.change > 0).length / valid.length * 100 : 0,
        revenueGrowth: average(stocks.map(stock => stock.rev)),
        foreign: stocks.reduce((sum, stock) => sum + (stock.foreign || 0), 0)
      };
    }).filter(row => row.count >= 3).sort((a, b) => (b.avgChange + b.breadth / 100) - (a.avgChange + a.breadth / 100));
    return { up, down, flat, avgChange, breadth, foreign, institutions, label, industries };
  }

  function percentile(values, value, higherIsBetter = true) {
    const valid = values.filter(item => item != null && Number.isFinite(item));
    if (!valid.length || value == null) return null;
    const rank = valid.filter(item => higherIsBetter ? item <= value : item >= value).length;
    return Math.round(rank / valid.length * 100);
  }

  function peerComparison(stock) {
    const peers = S.stocks.filter(item => item.industry === stock.industry);
    const definitions = [
      ['月營收年增', 'rev', true, '%'], ['ROE', 'roe', true, '%'], ['EPS', 'eps', true, ''],
      ['本益比', 'pe', false, ' 倍'], ['殖利率', 'yield', true, '%'], ['外資買賣超', 'foreign', true, ' 張']
    ];
    return {
      peerCount: peers.length,
      rows: definitions.map(([label, key, high, suffix]) => ({
        label, suffix, value: stock[key], median: median(peers.map(item => item[key])),
        percentile: percentile(peers.map(item => item[key]), stock[key], high)
      }))
    };
  }

  function nextRevenueWindow() {
    const now = new Date();
    const month = new Date(now.getFullYear(), now.getMonth() + 1, 1);
    return `${month.getFullYear()}-${String(month.getMonth() + 1).padStart(2, '0')} 上旬`;
  }

  function buildEvents(stock, indicators) {
    const events = [
      { icon: '▣', title: '下次月營收觀察窗', detail: `預估於 ${nextRevenueWindow()} 前後公布，實際時間以公司公告為準。`, level: 'info' }
    ];
    if (Math.abs(stock.change || 0) >= 7) events.push({ icon: '!', title: '單日波動較大', detail: `盤後漲跌幅 ${pct(stock.change)}，短線風險提高。`, level: 'warn' });
    if (indicators?.volumeRatio >= 1.5) events.push({ icon: '◫', title: '成交量明顯放大', detail: `近 5 日量能約為 20 日平均的 ${fmt(indicators.volumeRatio, 2)} 倍。`, level: 'warn' });
    if (indicators?.rsi14 >= 75) events.push({ icon: '▲', title: 'RSI 進入過熱區', detail: `RSI 14 為 ${fmt(indicators.rsi14)}，短線追價風險較高。`, level: 'warn' });
    if (indicators?.rsi14 <= 30) events.push({ icon: '▼', title: 'RSI 進入超賣區', detail: `RSI 14 為 ${fmt(indicators.rsi14)}，仍需觀察是否止跌。`, level: 'warn' });
    if (stock.rev != null && stock.rev < 0) events.push({ icon: '↘', title: '月營收年增為負', detail: `最新月營收年增 ${pct(stock.rev)}，成長動能需持續追蹤。`, level: 'bad' });
    if (stock.debt != null && stock.debt >= 70) events.push({ icon: '!', title: '負債比偏高', detail: `負債比 ${fmt(stock.debt)}%，財務彈性風險較高。`, level: 'bad' });
    if (stock.foreign != null && stock.foreign < 0) events.push({ icon: '◁', title: '外資當日賣超', detail: `外資買賣超 ${fmt(stock.foreign, 0)} 張。`, level: 'warn' });
    if (events.length === 1) events.push({ icon: '✓', title: '目前未偵測重大量價警示', detail: '仍應留意公司公告、產業消息及整體市場變化。', level: 'info' });
    return events;
  }
  function peerHtml(stock) {
    const peer = peerComparison(stock);
    return `<div class="card"><div class="muted">比較群組：${stock.industry}，共 ${peer.peerCount} 檔</div>${peer.rows.map(row => `<div class="patch-peer"><span>${row.label}</span><div><div class="patch-track"><span style="width:${row.percentile || 0}%"></span></div><small class="muted">同業中位數 ${row.median == null ? '—' : `${fmt(row.median)}${row.suffix}`}</small></div><b>${row.value == null ? '—' : `${fmt(row.value)}${row.suffix}`}<br><small class="muted">百分位 ${row.percentile == null ? '—' : row.percentile}</small></b></div>`).join('')}</div>`;
  }

  function marketIndustryHtml(stock) {
    const environment = marketEnvironment();
    const industry = environment.industries.find(item => item.industry === stock.industry);
    return `<div class="grid">${metric('大盤環境', environment.label)}${metric('上漲家數比', `${fmt(environment.breadth, 0)}%`)}${metric(`${stock.industry}平均漲跌`, industry ? pct(industry.avgChange) : reasonDash('同業不足'))}${metric(`${stock.industry}上漲家數`, industry ? `${fmt(industry.breadth, 0)}%` : reasonDash('同業不足'))}${metric('市場外資合計', `${fmt(environment.foreign, 0)} 張`)}${metric('產業外資合計', industry ? `${fmt(industry.foreign, 0)} 張` : reasonDash('同業不足'))}</div>`;
  }

  function eventHtml(stock, indicators) {
    return `<div class="card">${buildEvents(stock, indicators).map(event => `<div class="patch-event"><div class="patch-event-icon">${event.icon}</div><div><b>${event.title}</b><div class="muted">${event.detail}</div></div><span class="tag ${event.level === 'bad' ? 'bad' : event.level === 'warn' ? 'warn' : 'info'}">${event.level === 'bad' ? '風險' : event.level === 'warn' ? '注意' : '事件'}</span></div>`).join('')}</div>`;
  }

  function alertSection() {
    const store = refreshRuleAlerts();
    const events = Array.isArray(store.events) ? store.events : [];
    const unread = events.filter(event => !event.read).length;
    if (!events.length) return `<div class="card empty"><h3>尚無規則提醒</h3><p class="muted">系統會在正式資料日期更新後，比較自選股的分數、排名、營收、法人與技術條件。第一次載入只建立基準，不會產生舊訊號。</p></div>`;
    return `<div class="head alert-toolbar"><div><h3>站內規則提醒</h3><div class="muted">${unread ? `${unread} 則未讀` : '全部已讀'} · 僅儲存在此裝置</div></div>${unread ? '<button id="patchReadAlerts" class="btn secondary">全部標為已讀</button>' : ''}</div><div class="list alert-list">${events.map(event => `<button type="button" class="card alert-event ${event.read ? '' : 'unread'}" data-alert-key="${escapeText(event.key)}" data-alert-symbol="${escapeText(event.symbol)}"><div class="head"><span><b>${escapeText(event.name)} ${escapeText(event.symbol)}</b><small class="muted"> ${escapeText(groupLabel(event.group))}</small></span><time datetime="${escapeText(event.dataDate)}">${escapeText(event.dataDate)}</time></div><strong>${escapeText(event.title)}</strong><p class="muted">${escapeText(event.message)}</p></button>`).join('')}</div>`;
  }

  function watchSection() {
    const alertStore = refreshRuleAlerts();
    const latestAlert = new Map();
    for (const event of alertStore.events || []) if (!latestAlert.has(event.symbol)) latestAlert.set(event.symbol, event);
    const items = getWatchlist();
    const rows = items.map(item => ({ item, stock: S.stocks.find(stock => stock.symbol === item.symbol) })).filter(row => row.stock);
    if (!rows.length) return '<div class="card empty"><h3>尚未加入自選股票</h3><p class="muted">可在機會股或股票詳細頁加入。</p></div>';
    return `<div class="list two-col">${rows.map(({ stock }) => { const etf = instrumentGroup(stock) === 'etf'; const alert = latestAlert.get(stock.symbol); return `<div class="card clickable" data-detail="${stock.symbol}"><div class="head"><div><b>${stock.name}</b><div class="muted">${stock.symbol} · ${stock.industry}</div></div><button class="icon-btn" aria-label="從自選清單移除 ${escapeText(stock.name)}" data-watch="${stock.symbol}">移除</button></div>${alert ? `<div class="watch-alert ${alert.read ? '' : 'unread'}"><b>${escapeText(alert.title)}</b><span>${escapeText(alert.dataDate)}</span></div>` : ''}<div class="grid">${metric('目前價格', fmt(stock.close))}${metric('當日漲跌', `<span class="${cls(stock.change)}">${pct(stock.change)}</span>`)}${metric(etf ? '商品類型' : '月營收年增', etf ? 'ETF' : pct(stock.rev))}${metric(etf ? '成交量' : '機會分數', etf ? `${fmt(stock.volume, 0)} 張` : opportunityScore(stock))}</div><button class="btn" data-analysis="${stock.symbol}" style="width:100%;margin-top:10px">查看分析</button></div>`; }).join('')}</div>`;
  }

  function comparisonSection() {
    const stored = getCompareStore();
    const rows = comparisonRows();
    const exportButtons = `<div class="compare-export-grid" aria-label="分組排行榜匯出">
      <button class="btn secondary" data-export-group="listed">匯出上市 CSV</button>
      <button class="btn secondary" data-export-group="otc">匯出上櫃 CSV</button>
      <button class="btn secondary" data-export-group="etf">匯出 ETF CSV</button>
    </div>`;
    if (!rows.length) return `<div class="card empty compare-empty"><h3>尚未加入比較標的</h3><p class="muted">在機會排行榜或股票詳細頁按「＋比較」。一次只比較上市、上櫃或 ETF 的其中一組，最多 4 檔。</p>${exportButtons}</div>`;
    const group = stored.group || rows[0].group;
    const metrics = comparisonMetrics(group);
    return `<div class="head compare-toolbar"><div><h3>${groupLabel(group)}候選比較</h3><div class="muted">同市場、同一資料日期並排檢查 · ${rows.length}／4 檔</div></div><button id="exportComparison" class="btn">匯出比較 CSV</button></div>
      <div class="card compare-table-wrap"><table class="compare-table"><caption class="sr-only">${groupLabel(group)}候選比較表</caption><thead><tr><th scope="col">指標</th>${rows.map(row => `<th scope="col"><button class="compare-stock" data-detail="${row.stock.symbol}"><b>${escapeText(row.stock.name)}</b><span>${escapeText(row.stock.symbol)}</span></button><button class="compare-remove" type="button" data-compare-remove="${row.stock.symbol}" aria-label="從比較移除 ${escapeText(row.stock.name)}">移除</button></th>`).join('')}</tr></thead><tbody>${metrics.map(([label, reader]) => `<tr><th scope="row">${escapeText(label)}</th>${rows.map(row => `<td>${escapeText(reader(row))}</td>`).join('')}</tr>`).join('')}</tbody></table></div>
      <div class="notice"><b>比較限制</b><br>這裡只整理既有公開資料與量化結果，不重新計分；正式排名尚未封存時會明確顯示「累積中」。不同市場不放在同一張表。</div>
      ${exportButtons}`;
  }

  function minePage() {
    const unread = refreshRuleAlerts().events?.filter(event => !event.read).length || 0;
    const compareCount = getCompareStore().symbols.length;
    const section = patchState.mineTab === 'watch' ? watchSection()
      : patchState.mineTab === 'alerts' ? alertSection()
        : comparisonSection();
    return `<h2>我的</h2><div class="patch-tabs"><button data-patch-mine="watch" class="${patchState.mineTab === 'watch' ? 'active' : ''}">自選清單</button><button data-patch-mine="compare" class="${patchState.mineTab === 'compare' ? 'active' : ''}">候選比較${compareCount ? `<span class="nav-count">${compareCount}</span>` : ''}</button><button data-patch-mine="alerts" class="${patchState.mineTab === 'alerts' ? 'active' : ''}">規則提醒${unread ? `<span class="nav-count">${unread}</span>` : ''}</button></div>${section}${disclaimer()}`;
  }

  function bindPatch() {
    qa('.ultimate-card .smart-actions').forEach(actions => {
      const symbol = q('[data-analysis]', actions)?.dataset.analysis;
      if (!symbol || q('[data-compare]', actions)) return;
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'btn secondary compare-action';
      button.dataset.compare = symbol;
      actions.append(button);
    });
    syncCompareButtons();
    qa('[data-compare]').forEach(button => button.onclick = event => {
      event.stopPropagation();
      toggleComparison(button.dataset.compare);
    });
    qa('[data-compare-remove]').forEach(button => button.onclick = event => {
      event.stopPropagation();
      toggleComparison(button.dataset.compareRemove);
    });
    q('#exportComparison')?.addEventListener('click', exportComparison);
    qa('[data-export-group]').forEach(button => button.onclick = () => exportGroupRanking(button.dataset.exportGroup));
    qa('[data-patch-mine]').forEach(button => button.onclick = () => { patchState.mineTab = button.dataset.patchMine; render(); });
    q('#patchReadAlerts')?.addEventListener('click', () => {
      const store = getAlertStore();
      store.events = (store.events || []).map(event => ({ ...event, read: true }));
      setAlertStore(store); render();
    });
    qa('[data-alert-key]').forEach(button => button.onclick = () => {
      const store = getAlertStore();
      const event = (store.events || []).find(item => item.key === button.dataset.alertKey);
      store.events = (store.events || []).map(item => item.key === button.dataset.alertKey ? { ...item, read: true } : item);
      setAlertStore(store);
      if (event?.symbol) openDetail(event.symbol);
    });
  }

  const originalBind = bind;
  bind = function patchedBind() { originalBind(); bindPatch(); };
  const originalRender = render;
  render = function patchedRender() {
    qa('.bottom-nav button').forEach(button => button.classList.toggle('active', button.dataset.tab === S.tab));
    if (S.tab === 'mine') { app.innerHTML = minePage(); bind(); return; }
    originalRender();
  };

  function updateNavigation() {
    const nav = q('.bottom-nav');
    if (!nav) return;
    const watchButton = q('[data-tab="watch"]', nav);
    if (watchButton) { watchButton.dataset.tab = 'mine'; watchButton.innerHTML = '<span>◎</span>我的'; }
  }

  updateNavigation();
  render();
})();
