(() => {
  'use strict';

  // The v20 shell loads summary/read-model APIs first. Legacy all-market
  // fundamentals are deferred; individual detail is fetched on demand.
  globalThis.twssV20Active = true;

  const API = '/api/v20';
  const CACHE_PREFIX = 'twss-v20-public-cache:';
  const VALID_TABS = new Set(['home', 'short', 'medium', 'watchlist', 'analysis']);
  const HORIZONS = { short: [2, 3, 5, 10], medium: [20, 40, 60] };
  const DEFAULT_HORIZON = { short: 5, medium: 40 };
  const stateLabels = {
    cache: ['已載入快取資料', 'cache'],
    cached: ['已載入快取資料', 'cache'],
    base_ready: ['基礎分析已完成', 'complete'],
    enriching: ['背景資料補齊中', 'refreshing'],
    refreshing: ['正在取得最新資料', 'refreshing'],
    complete: ['已完成更新', 'complete'],
    partial: ['部分資料不足', 'partial'],
    error: ['API 更新失敗', 'error']
  };
  const num = value => value != null && Number.isFinite(Number(value)) ? Number(value) : null;
  const dateKey = value => /^\d{4}-\d{2}-\d{2}/.test(String(value || '')) ? String(value).slice(0, 10) : '';
  const displayNumber = (value, digits = 1) => num(value) == null ? '資料不足' : Number(value).toLocaleString('zh-TW', { maximumFractionDigits: digits });
  const displayPercent = (value, digits = 1) => num(value) == null ? '資料不足' : `${Number(value) > 0 ? '+' : ''}${Number(value).toFixed(digits)}%`;
  const probability = value => num(value) == null ? '資料不足' : `${Number(value).toFixed(1)}%`;
  const safeArray = value => Array.isArray(value) ? value : [];
  const first = (...values) => values.find(value => value != null && value !== '');
  const strategyLabels = {
    momentum_breakout: '動能突破',
    trend_pullback: '趨勢拉回',
    institutional_flow: '法人籌碼',
    event_catalyst: '事件催化',
    oversold_rebound: '超跌反彈',
    growth_momentum: '成長動能',
    institutional_positioning: '法人布局',
    industry_trend: '產業趨勢',
    medium_breakout: '中期突破',
    value_recovery: '價值回升',
    cycle_recovery: '景氣復甦'
  };
  const strategyLabel = value => value ? (strategyLabels[value] || value) : '策略待確認';
  const localizeStrategyText = value => {
    let text = String(value || '');
    Object.entries(strategyLabels).forEach(([key, label]) => { text = text.replaceAll(key, label); });
    return text;
  };

  function readCache(key) {
    try {
      const parsed = JSON.parse(localStorage.getItem(`${CACHE_PREFIX}${key}`) || 'null');
      return parsed?.payload?.version === '20.0' ? parsed.payload : null;
    } catch { return null; }
  }

  function writeCache(key, payload) {
    if (!payload || payload.version !== '20.0') return;
    try { localStorage.setItem(`${CACHE_PREFIX}${key}`, JSON.stringify({ savedAt: new Date().toISOString(), payload })); } catch { /* cache is optional */ }
  }

  function unwrapDailyReport(value) {
    const payload = value?.data && typeof value.data === 'object' ? value.data : value;
    if (!payload || typeof payload !== 'object') return null;
    return { meta: payload, report: payload.report && typeof payload.report === 'object' ? payload.report : payload };
  }

  function readDailyReportCache() {
    try { return unwrapDailyReport(JSON.parse(localStorage.getItem('twss-v19-daily-report-cache') || 'null')); }
    catch { return null; }
  }

  function rankingState(model) {
    const cached = readCache(`rankings:${model}`);
    return {
      items: safeArray(cached?.items),
      nextCursor: cached?.nextCursor || null,
      totalEstimate: cached?.totalEstimate || 0,
      dataDate: cached?.dataDate || null,
      completeness: cached?.completeness || 0,
      dataCompleteness: cached?.dataCompleteness || cached?.completeness || 0,
      publicationPhase: cached?.publicationPhase || (cached ? 'cached' : 'refreshing'),
      enrichmentPending: cached?.enrichmentPending || 0,
      degradedSources: safeArray(cached?.degradedSources),
      phase: cached ? 'cache' : 'refreshing',
      loading: false,
      loaded: false,
      error: '',
      horizon: cached?.horizon || DEFAULT_HORIZON[model],
      market: cached?.filters?.market || 'all',
      industry: cached?.filters?.industry || '',
      sort: cached?.sort || 'expected_value_desc',
      search: cached?.filters?.search || '',
      requestId: 0
    };
  }

  const cachedHome = readCache('home');
  const cachedDailyReport = unwrapDailyReport(cachedHome?.dailyReport) || readDailyReportCache();
  const v20 = {
    home: cachedHome,
    homePhase: cachedHome ? 'cache' : 'refreshing',
    homeError: '',
    dailyReport: cachedDailyReport,
    dailyPhase: cachedDailyReport ? 'cache' : 'refreshing',
    dailyError: '',
    pages: { short: rankingState('short'), medium: rankingState('medium') },
    detailCache: new Map(),
    watchAttempted: new Set(),
    watchErrors: new Map(),
    watchLoading: false,
    mineTab: 'watchlist',
    portfolio: [],
    portfolioOwner: '',
    portfolioLoaded: false,
    portfolioLoading: false,
    portfolioSaving: false,
    portfolioError: '',
    portfolioMessage: '',
    portfolioEditId: '',
    portfolioDraft: null,
    portfolioAttempted: new Set(),
    portfolioErrors: new Map(),
    newsVisible: 5,
    analysisSymbol: '',
    analysisMessage: ''
  };

  function enforceDarkOnly() {
    document.documentElement.dataset.theme = 'dark';
    document.documentElement.style.colorScheme = 'dark';
    document.body.classList.add('v20-app');
    ['twss-theme-v19', 'twss-theme', 'theme', 'color-scheme'].forEach(key => localStorage.removeItem(key));
    document.querySelectorAll('[data-theme-toggle],#themeToggle,.theme-toggle').forEach(node => node.remove());
  }

  async function apiJson(path, timeout = 9000) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    try {
      const response = await fetch(`${API}${path}`, { cache: 'no-store', signal: controller.signal, headers: { accept: 'application/json' } });
      const payload = await response.json().catch(() => null);
      if (!response.ok || !payload) throw new Error(payload?.error?.message || `HTTP ${response.status}`);
      return payload;
    } finally { clearTimeout(timer); }
  }

  function statusBanner(payload, phase, error = '') {
    const state = error ? 'error' : phase === 'refreshing' ? 'refreshing' : phase === 'cache' ? 'cache' : payload?.publicationPhase || payload?.dataState || 'partial';
    const [label, className] = stateLabels[state] || stateLabels.partial;
    const date = payload?.dataDate || S.date || '日期待補';
    const degraded = safeArray(payload?.degradedSources);
    const pending = num(payload?.enrichmentPending);
    return `<div class="v20-data-status ${className}" role="status"><span class="v20-status-dot"></span><div><b>${label}</b><small>資料日期 ${esc(date)}${pending > 0 ? ` · 背景待補 ${displayNumber(pending, 0)} 筆` : degraded.length ? ` · ${degraded.length} 個來源待補` : ''}</small></div>${state === 'refreshing' || state === 'enriching' ? '<span class="spinner" aria-hidden="true"></span>' : ''}</div>`;
  }

  function pageHero(eyebrow, title, description, status = '') {
    return `<header class="v20-page-hero"><div><span class="v20-eyebrow">${esc(eyebrow)}</span><h2>${esc(title)}</h2><p>${esc(description)}</p></div>${status}</header>`;
  }

  function marketValue(value) {
    return first(value?.value, value?.close, value?.index, value?.price, value?.settlement);
  }

  function marketChange(value) {
    return first(value?.changePercent, value?.change_pct, value?.change);
  }

  function marketCard(label, value) {
    const quote = marketValue(value);
    const change = marketChange(value);
    const source = first(value?.source, value?.provider, '來源待補');
    const contract = value?.contractMonth ? ` · ${value.contractMonth}` : '';
    const session = value?.session ? ` · ${value.session}` : '';
    return `<article class="v20-market-card"><small>${esc(label)}</small><strong>${displayNumber(quote, 2)}</strong><b class="${num(change) > 0 ? 'up' : num(change) < 0 ? 'down' : 'muted'}">${num(change) == null ? '資料待補' : displayPercent(change, 2)}</b><em>${esc(source)}${esc(contract)}${esc(session)}</em><time>${esc(first(value?.dataDate, value?.date, '日期待補'))}</time></article>`;
  }

  function forecastFor(row) {
    return row?.forecasts?.[String(row.horizon)] || Object.values(row?.forecasts || {})[0] || {};
  }

  function predictionFor(row, forecast = forecastFor(row)) {
    if (row?.predictionState && typeof row.predictionState === 'object') return row.predictionState;
    if (forecast?.predictionState && typeof forecast.predictionState === 'object') return forecast.predictionState;
    if (forecast?.dataState === 'calibrated') return { status: 'calibrated', publicForecast: true, reason: '已完成 Walk-forward 校準。' };
    if (forecast?.dataState === 'quant_bootstrap') return { status: 'not_calibrated', publicForecast: false, reason: '目前只有規則初估，尚未完成 Walk-forward 校準。' };
    return { status: 'not_generated', publicForecast: false, reason: '模型尚未產生可公開的預測資料。' };
  }

  function modelCard(row, rank = null) {
    const forecast = forecastFor(row);
    const prediction = predictionFor(row, forecast);
    const reference = row.legacyReference === true;
    return `<article class="card v20-model-card ${reference ? 'reference' : ''}" data-v20-detail="${esc(row.symbol)}">
      <div class="v20-card-head"><span class="v20-rank">${rank || row.rank || '—'}</span><div class="v20-card-name"><b>${esc(row.name || row.symbol)}</b><small>${esc(row.symbol)} · ${esc(first(row.market, row.group, '市場待補'))}</small></div><div class="v20-card-score"><small>${reference ? '舊資料參考' : '機會分數'}</small><strong>${reference ? '—' : displayNumber(row.opportunityScore, 0)}</strong></div></div>
      <p class="v20-summary">${esc(localizeStrategyText(first(row.summary, safeArray(row.reasons)[0], reference ? 'v20 模型建立中，暫不提供推測分數。' : '分析原因待補')))}</p>
      <div class="v20-chip-row"><span>${esc(strategyLabel(row.strategy))}</span><span>風險 ${displayNumber(row.riskScore, 0)}</span><span>信心 ${probability(row.confidence)}</span><span>資料 ${esc(first(row.dataDate, '日期待補'))}</span></div>
      ${prediction.publicForecast ? `<div class="v20-forecast-row"><div><small>${row.horizon} 日上漲機率</small><b>${probability(forecast.upProbability)}</b></div><div><small>預估淨報酬</small><b>${displayPercent(forecast.expectedNetReturn)}</b></div><div><small>建議</small><b>${esc(row.recommendedAction || '資料不足')}</b></div></div>` : `<div class="v20-forecast-row"><div><small>${row.horizon} 日預測</small><b>尚未校準</b></div><div><small>目前可參考</small><b>分數與風險</b></div><div><small>建議</small><b>${esc(row.recommendedAction || '觀察')}</b></div></div>`}
      <div class="row v20-card-actions"><button class="btn secondary grow" type="button" data-watch="${esc(row.symbol)}">${isWatched(row.symbol) ? '✓ 已自選' : '＋ 加入自選'}</button><button class="btn grow" type="button" data-v20-detail="${esc(row.symbol)}">查看分析</button></div>
    </article>`;
  }

  function compactList(rows, model) {
    if (!rows.length) return '<div class="card v20-empty"><b>模型資料正在建立</b><p>先顯示頁面，完成校準後會自動補上排行，不會使用猜測數字。</p></div>';
    return `<div class="v20-top-list">${rows.slice(0, 5).map((row, index) => `<button type="button" data-v20-detail="${esc(row.symbol)}"><span>${index + 1}</span><div><b>${esc(row.name || row.symbol)}</b><small>${esc(row.symbol)} · ${esc(first(strategyLabel(row.strategy), row.industry, '資料待補'))}</small></div><strong>${row.legacyReference ? '—' : displayNumber(row.opportunityScore, 0)}</strong><i>›</i></button>`).join('')}</div><button class="v20-more-link" type="button" data-tab-jump="${model}">查看完整${model === 'short' ? '短期' : '中期'}排行 →</button>`;
  }

  function globalStrip(market) {
    const context = market?.globalContext || {};
    const definitions = [[['nasdaq'], 'NASDAQ'], [['sp500'], 'S&P 500'], [['sox'], 'SOX'], [['tsmAdr'], '台積電 ADR'], [['nvidia', 'nvda'], 'NVIDIA'], [['vix'], 'VIX'], [['us10y', 'usTreasury'], '美債 10Y'], [['usdTwd', 'twdUsd'], 'USD/TWD']];
    const rows = definitions.flatMap(([keys, label]) => {
      const value = keys.map(key => context[key]).find(Boolean);
      return value ? [[label, value]] : [];
    });
    if (!rows.length) return '<div class="v20-inline-note">國際指標快取尚未同步；目前保留其他已載入資料，不顯示推測值。</div>';
    return `<div class="v20-global-strip">${rows.map(([label, value]) => `<div><small>${esc(value?.label || (value?.proxy ? `${label}（ETF 代理）` : label))}</small><b>${displayNumber(marketValue(value), 2)}</b><span>${num(marketChange(value)) == null ? '—' : displayPercent(marketChange(value), 2)}</span><time>${esc(first(value?.dataDate, '日期待補'))}</time><em>${esc(first(value?.source, value?.symbol, '來源待補'))}</em></div>`).join('')}</div>`;
  }

  function dailyReportSection() {
    const wrapped = v20.dailyReport;
    const report = wrapped?.report || {};
    const meta = wrapped?.meta || {};
    const strength = report.marketStrength || {};
    const institutional = report.institutionalDirection || {};
    const industries = safeArray(report.hotIndustries).slice(0, 4);
    const focus = safeArray(first(report.watchStocks, report.opportunityStocks)).slice(0, 4);
    const risks = safeArray(first(report.mainRisks, report.risks)).slice(0, 3);
    const changes = safeArray(report.watchlistChanges).slice(0, 4);
    if (!wrapped) return `<section class="v20-section"><div class="v20-section-title"><div><span>DAILY AI BRIEF</span><h3>AI 每日報告</h3></div></div><div class="card v20-empty">${v20.dailyPhase === 'refreshing' ? '<span class="spinner"></span> 正在背景讀取最近一次報告，首頁其他內容可先使用。' : '每日報告更新失敗，保留其他已載入內容。'}</div></section>`;
    return `<section class="v20-section"><div class="v20-section-title"><div><span>DAILY AI BRIEF</span><h3>AI 每日報告</h3></div><small>${esc(meta.dataDate || '日期待補')}</small></div><article class="card v20-daily-report">${statusBanner({ dataState: meta.updateStatus || meta.dataState, dataDate: meta.dataDate, publicationPhase: meta.publicationPhase, enrichmentPending: meta.enrichmentPending, degradedSources: meta.degradedSources }, v20.dailyPhase, v20.dailyError)}<p class="v20-daily-lead">${esc(first(report.oneLine, report.todayInOneSentence, '今日市場結論待補'))}</p><div class="v20-daily-grid"><div><small>市場強弱</small><b>${esc(first(strength.level, strength.label, '資料不足'))}</b><p>${esc(first(strength.explanation, '等待市場廣度資料補齊。'))}</p></div><div><small>法人方向</small><b>${esc(first(institutional.direction, institutional.label, '資料不足'))}</b><p>${esc(first(institutional.explanation, '等待法人資料補齊。'))}</p></div></div>${industries.length ? `<div class="v20-daily-block"><h4>熱門產業</h4><div class="v20-chip-row">${industries.map(item => `<span>${esc(item.industry || item.name || item)}${num(item.averageChangePct) == null ? '' : ` ${displayPercent(item.averageChangePct)}`}</span>`).join('')}</div></div>` : ''}${focus.length ? `<div class="v20-daily-block"><h4>值得關注</h4><div class="v20-report-stocks">${focus.map(item => `<button type="button" data-v20-detail="${esc(item.symbol)}"><b>${esc(item.name || item.symbol)}</b><small>${esc(item.symbol)} · ${esc(first(item.whyNotice, item.advantage, '查看量化分析'))}</small></button>`).join('')}</div></div>` : ''}${risks.length ? `<div class="v20-daily-block"><h4>主要風險</h4><ul>${risks.map(item => `<li><b>${esc(item.title || '風險提醒')}</b> ${esc(item.explanation || item.risk || item)}</li>`).join('')}</ul></div>` : ''}<div class="v20-daily-block"><h4>自選股變化</h4>${changes.length ? `<ul>${changes.map(item => `<li>${esc(typeof item === 'string' ? item : first(item.explanation, item.message, item.title, item.symbol))}</li>`).join('')}</ul>` : '<p class="muted">目前沒有已驗證的重要變化。</p>'}</div></article></section>`;
  }

  function homePageV20() {
    const home = v20.home || {};
    const market = home.market || {};
    const officialIndices = new Map(safeArray(globalThis.twssV19Benchmarks?.marketIndices).map(item => [String(item.code || ''), item]));
    const reportNews = safeArray(first(v20.dailyReport?.report?.importantNewsAndAnnouncements, v20.dailyReport?.report?.importantNews));
    const news = safeArray(home.importantNews).length ? safeArray(home.importantNews) : reportNews;
    const resolvedSources = new Set([
      marketValue(officialIndices.get('taiex')) != null && 'taiex_official_index',
      marketValue(officialIndices.get('tpex')) != null && 'tpex_official_index',
      marketValue(officialIndices.get('tx')) != null && 'tx_futures',
    ].filter(Boolean));
    let visibleDegraded = safeArray(home.degradedSources).filter(source => !resolvedSources.has(source));
    const globalMissing = visibleDegraded.filter(source => source === 'international_context' || source.startsWith('global_'));
    if (globalMissing.length > 1) {
      visibleDegraded = visibleDegraded.filter(source => !globalMissing.includes(source));
      visibleDegraded.push('international_context');
    }
    const state = statusBanner({
      ...home,
      dataState: visibleDegraded.length ? home.dataState : 'complete',
      degradedSources: visibleDegraded,
    }, v20.homePhase, v20.homeError);
    return `<div class="v20-dashboard">
      ${pageHero('MARKET INTELLIGENCE · v20', '今日重點', '先看結論，再展開需要的細節。', state)}
      <section class="v20-section"><div class="v20-section-title"><div><span>MARKET REGIME</span><h3>今日市場環境</h3></div><strong>${esc(market.regime || '資料不足')}</strong></div>
        <div class="card v20-market-panel"><div class="v20-market-grid">${marketCard('加權指數', officialIndices.get('taiex') || market.taiex)}${marketCard('櫃買指數', officialIndices.get('tpex') || market.tpex)}${marketCard('台指期', officialIndices.get('tx') || market.txFutures)}</div><div class="v20-regime-line"><span>市場強弱</span><b>${displayNumber(market.regimeScore, 0)} / 100</b><span>信心 ${probability(market.confidence)}</span></div>${globalStrip(market)}</div>
      </section>
      ${dailyReportSection()}
      <div class="v20-home-columns"><section class="v20-section"><div class="v20-section-title"><div><span>SHORT-TERM</span><h3>短期 Top 5</h3></div><small>2／3／5／10 日</small></div>${compactList(safeArray(home.shortTop), 'short')}</section>
      <section class="v20-section"><div class="v20-section-title"><div><span>MID-TERM</span><h3>中期 Top 5</h3></div><small>20／40／60 日</small></div>${compactList(safeArray(home.mediumTop), 'medium')}</section></div>
      <section class="v20-section"><div class="v20-section-title"><div><span>DISCLOSURES</span><h3>重要新聞與公告</h3></div><small>${news.length ? `顯示 ${Math.min(v20.newsVisible, news.length)}／${news.length} 則` : '資料待補'}</small></div>${news.length ? `<div class="card v20-news-list">${news.slice(0, v20.newsVisible).map(item => `<article><div><b>${esc(item.title || '未命名公告')}</b><small>${esc(first(item.companyName, item.source, '公開來源'))} · ${esc(first(item.eventDate, item.publishedAt?.slice?.(0, 10), '日期待補'))}</small></div><span class="tag ${item.sentimentLabel === 'harm' ? 'bad' : item.sentimentLabel === 'benefit' ? '' : 'info'}">${item.sentimentLabel === 'harm' ? '風險' : item.sentimentLabel === 'benefit' ? '正向' : '中性'}</span></article>`).join('')}</div>${v20.newsVisible < news.length ? '<button id="v20NewsMore" class="v20-more-link" type="button">載入更多新聞與公告</button>' : ''}` : '<div class="card v20-empty">目前沒有完成驗證的重要公告。</div>'}</section>
      ${disclaimer()}
    </div>`;
  }

  function rankingFilters(model, page) {
    const label = model === 'short' ? '短期' : '中期';
    return `<div class="card v20-filters"><div class="v20-filter-grid"><label>觀察期間<select id="v20Horizon">${HORIZONS[model].map(value => `<option value="${value}" ${page.horizon === value ? 'selected' : ''}>${value} 個交易日</option>`).join('')}</select></label><label>市場<select id="v20Market"><option value="all">全部</option><option value="listed" ${page.market === 'listed' ? 'selected' : ''}>上市</option><option value="otc" ${page.market === 'otc' ? 'selected' : ''}>上櫃</option><option value="etf" ${page.market === 'etf' ? 'selected' : ''}>ETF</option></select></label><label>產業<input id="v20Industry" value="${esc(page.industry)}" placeholder="全部產業"></label><label>排序<select id="v20Sort"><option value="expected_value_desc" ${page.sort === 'expected_value_desc' ? 'selected' : ''}>交易期望值</option><option value="score_desc" ${page.sort === 'score_desc' ? 'selected' : ''}>機會分數</option><option value="risk_asc" ${page.sort === 'risk_asc' ? 'selected' : ''}>風險較低</option><option value="probability_desc" ${page.sort === 'probability_desc' ? 'selected' : ''}>上漲機率</option><option value="change_desc" ${page.sort === 'change_desc' ? 'selected' : ''}>排名上升</option></select></label></div><div class="search-row"><input id="v20Search" value="${esc(page.search)}" inputmode="search" placeholder="搜尋股票代號或名稱" aria-label="搜尋${label}機會股"><button id="v20SearchBtn" class="btn" type="button">搜尋</button></div></div>`;
  }

  function rankingPageV20(model) {
    const page = v20.pages[model];
    const label = model === 'short' ? '短期機會股' : '中期機會股';
    const description = model === 'short' ? '尋找量價、突破、籌碼與事件形成的短波段。' : '尋找成長、產業趨勢、法人布局與中期趨勢。';
    const status = statusBanner({ dataState: page.phase, dataDate: page.dataDate, completeness: page.completeness, dataCompleteness: page.dataCompleteness, publicationPhase: page.publicationPhase, enrichmentPending: page.enrichmentPending, degradedSources: page.degradedSources }, page.phase, page.error);
    return `<div class="v20-ranking-page">${pageHero(model === 'short' ? 'SHORT-TERM MODEL' : 'MID-TERM MODEL', label, description, status)}${rankingFilters(model, page)}
      <div class="v20-results-head"><div><b>${page.items.length} 檔</b><small>資料日期 ${esc(page.dataDate || S.date || '待補')}</small></div><span>分數與風險分開呈現</span></div>
      <div class="v20-card-list">${page.items.map((row, index) => modelCard(row, index + 1)).join('') || `<div class="card v20-empty">${page.loading ? '<span class="spinner"></span> 正在局部更新排行，其他頁面仍可使用。' : '目前沒有通過硬性條件且資料完整的股票。'}</div>`}</div>
      ${page.nextCursor ? `<button id="v20LoadMore" class="btn secondary v20-load-more" type="button" ${page.loading ? 'disabled' : ''}>${page.loading ? '載入中…' : '載入更多 20 檔'}</button>` : ''}${disclaimer()}</div>`;
  }

  function watchlistRowsV20() {
    const watched = getWatchlist();
    return watched.map(item => {
      const symbol = String(item.symbol || '');
      const detail = v20.detailCache.get(symbol) || readCache(`stock:${symbol}`);
      const short = safeArray(detail?.short).find(signal => signal.horizon === DEFAULT_HORIZON.short) || safeArray(detail?.short)[0];
      const medium = safeArray(detail?.medium).find(signal => signal.horizon === DEFAULT_HORIZON.medium) || safeArray(detail?.medium)[0];
      return { item, detail, short, medium, stock: detail?.stock || S.stocks.find(stock => String(stock.symbol) === symbol) };
    }).filter(({ item }) => item.symbol);
  }

  function watchlistSectionV20() {
    const rows = watchlistRowsV20();
    return rows.length ? `<div class="v20-card-list">${rows.map(({ item, detail, short, medium, stock }) => {
        const reminder = localizeStrategyText(first(v20.watchErrors.get(String(item.symbol)), safeArray(short?.risks)[0], safeArray(medium?.risks)[0], safeArray(short?.reasons)[0], safeArray(medium?.reasons)[0], detail ? '目前沒有已驗證的新提醒。' : '正在背景載入 AI 分析。'));
        return `<article class="card v20-watch-card" data-v20-detail="${esc(item.symbol)}"><div class="head"><div><b>${esc(stock?.name || item.symbol)}</b><small>${esc(item.symbol)} · ${esc(first(stock?.market, '市場待補'))}</small></div><button type="button" class="icon-btn" data-watch="${esc(item.symbol)}">移除</button></div><div class="v20-watch-metrics"><div><small>最新價格</small><b>${displayNumber(first(stock?.close, stock?.price), 2)}</b></div><div><small>短期機會／風險</small><b>${displayNumber(short?.opportunityScore, 0)}／${displayNumber(short?.riskScore, 0)}</b></div><div><small>中期機會／風險</small><b>${displayNumber(medium?.opportunityScore, 0)}／${displayNumber(medium?.riskScore, 0)}</b></div><div><small>資料日期</small><b>${esc(first(detail?.dataDate, stock?.priceDate, S.date, '待補'))}</b></div></div><div class="v20-inline-note"><b>重要提醒：</b>${esc(reminder)}</div><button type="button" class="btn v20-full" data-v20-detail="${esc(item.symbol)}">查看短中期分析</button></article>`;
      }).join('')}</div>` : '<div class="card v20-empty"><h3>尚未加入自選股票</h3><p>可在短期、中期排行榜或個股分析中加入。</p></div>';
  }

  function portfolioStock(symbol) {
    const detail = v20.detailCache.get(symbol) || readCache(`stock:${symbol}`);
    return { detail, stock: detail?.stock || S.stocks.find(item => String(item.symbol) === symbol) };
  }

  function portfolioFormV20() {
    const editing = v20.portfolio.find(item => item.id === v20.portfolioEditId);
    const values = editing || v20.portfolioDraft || {};
    return `<form id="v20PortfolioForm" class="card v20-portfolio-form"><div class="head"><div><h3>${editing ? '修改目前持股' : '新增目前持股'}</h3><p class="muted">只保存目前股數與平均成本，不建立交易明細。</p></div>${editing ? '<button id="v20PortfolioCancel" class="icon-btn" type="button">取消</button>' : ''}</div><div class="v20-portfolio-form-grid"><label>股票代號<input id="v20PortfolioSymbol" name="symbol" maxlength="12" inputmode="latin" required value="${esc(values.symbol || '')}" ${editing ? 'readonly' : ''} placeholder="例如 2330"></label><label>股票名稱（選填）<input id="v20PortfolioName" name="stockName" maxlength="120" value="${esc(values.stock_name || '')}" placeholder="留空會自動帶入"></label><label>目前股數<input id="v20PortfolioQuantity" name="quantity" type="number" min="0.0001" step="any" required value="${esc(values.quantity || '')}" placeholder="例如 1000"></label><label>平均成本<input id="v20PortfolioCost" name="averageCost" type="number" min="0.0001" step="any" required value="${esc(values.average_cost || '')}" placeholder="每股成本"></label></div><label>備註（選填）<textarea id="v20PortfolioNote" name="note" maxlength="1000" placeholder="最多 1000 字">${esc(values.note || '')}</textarea></label>${v20.portfolioMessage ? `<div class="v20-form-message">${esc(v20.portfolioMessage)}</div>` : ''}<button class="btn v20-full" type="submit" ${v20.portfolioSaving ? 'disabled' : ''}>${v20.portfolioSaving ? '儲存中…' : editing ? '儲存修改' : '新增持股'}</button></form>`;
  }

  function portfolioSectionV20() {
    if (!S.session || !sessionUserId()) return '<div class="card v20-empty"><h3>登入後使用目前持股</h3><p>持股資料只會保存在你的 CORE 雲端帳戶。</p><button id="v20PortfolioLogin" class="btn" type="button">前往登入</button></div>';
    const positions = v20.portfolio;
    const list = positions.length ? `<div class="v20-card-list">${positions.map(position => {
      const symbol = String(position.symbol || '');
      const { detail, stock } = portfolioStock(symbol);
      const price = num(first(stock?.close, stock?.price));
      const quantity = num(position.quantity);
      const averageCost = num(position.average_cost);
      const marketValue = price != null && quantity != null ? price * quantity : null;
      const profit = price != null && quantity != null && averageCost != null ? (price - averageCost) * quantity : null;
      const profitPct = price != null && averageCost > 0 ? (price / averageCost - 1) * 100 : null;
      const quoteError = v20.portfolioErrors.get(symbol);
      return `<article class="card v20-portfolio-card"><div class="head"><div><b>${esc(position.stock_name || stock?.name || symbol)}</b><small>${esc(symbol)} · ${esc(first(stock?.market, '市場待補'))}</small></div><div class="row"><button class="icon-btn" type="button" data-portfolio-edit="${esc(position.id)}">修改</button><button class="icon-btn v20-delete" type="button" data-portfolio-delete="${esc(position.id)}">刪除</button></div></div><div class="v20-portfolio-metrics"><div><small>目前股數</small><b>${displayNumber(quantity, 4)}</b></div><div><small>平均成本</small><b>${displayNumber(averageCost, 2)}</b></div><div><small>最新價格</small><b>${price == null ? '行情待補' : displayNumber(price, 2)}</b></div><div><small>部位市值</small><b>${marketValue == null ? '行情待補' : displayNumber(marketValue, 0)}</b></div><div><small>未實現損益</small><b class="${profit > 0 ? 'up' : profit < 0 ? 'down' : 'muted'}">${profit == null ? '行情待補' : displayNumber(profit, 0)}</b></div><div><small>損益率</small><b class="${profitPct > 0 ? 'up' : profitPct < 0 ? 'down' : 'muted'}">${profitPct == null ? '行情待補' : displayPercent(profitPct, 2)}</b></div></div>${position.note ? `<p class="v20-portfolio-note">${esc(position.note)}</p>` : ''}${quoteError ? `<div class="v20-inline-note">${esc(quoteError)}</div>` : ''}<div class="row"><button type="button" class="btn secondary grow" data-v20-detail="${esc(symbol)}">查看分析</button></div><small class="muted">行情資料日期 ${esc(first(detail?.dataDate, stock?.priceDate, S.date, '待補'))}</small></article>`;
    }).join('')}</div>` : v20.portfolioLoading ? '<div class="card v20-empty"><span class="spinner"></span> 正在載入持股資料…</div>' : '<div class="card v20-empty"><h3>尚未建立目前持股</h3><p>請手動輸入目前股數與平均成本。</p></div>';
    return `${portfolioFormV20()}${v20.portfolioError ? `<div class="notice">${esc(v20.portfolioError)}</div>` : ''}${list}`;
  }

  function reminderSectionV20() {
    const symbols = [...new Set([...getWatchlist().map(item => String(item.symbol || '')), ...v20.portfolio.map(item => String(item.symbol || ''))].filter(Boolean))];
    if (!symbols.length) return '<div class="card v20-empty"><h3>目前沒有重要提醒</h3><p>加入自選或目前持股後，這裡會整理短中期風險。</p></div>';
    return `<div class="v20-card-list">${symbols.map(symbol => {
      const { detail, stock } = portfolioStock(symbol);
      const short = safeArray(detail?.short).find(signal => signal.horizon === DEFAULT_HORIZON.short) || safeArray(detail?.short)[0];
      const medium = safeArray(detail?.medium).find(signal => signal.horizon === DEFAULT_HORIZON.medium) || safeArray(detail?.medium)[0];
      const message = localizeStrategyText(first(v20.watchErrors.get(symbol), v20.portfolioErrors.get(symbol), safeArray(short?.risks)[0], safeArray(medium?.risks)[0], detail ? '目前沒有已驗證的新提醒。' : '分析資料待補。'));
      return `<article class="card v20-reminder-card"><div class="head"><div><b>${esc(stock?.name || v20.portfolio.find(item => item.symbol === symbol)?.stock_name || symbol)}</b><small>${esc(symbol)} · ${esc(first(detail?.dataDate, stock?.priceDate, S.date, '日期待補'))}</small></div><button class="icon-btn" type="button" data-v20-detail="${esc(symbol)}">查看</button></div><div class="v20-watch-metrics"><div><small>短期風險</small><b>${displayNumber(short?.riskScore, 0)}</b></div><div><small>中期風險</small><b>${displayNumber(medium?.riskScore, 0)}</b></div></div><div class="v20-inline-note">${esc(message)}</div></article>`;
    }).join('')}</div>`;
  }

  function watchlistPageV20() {
    const section = v20.mineTab === 'portfolio' ? portfolioSectionV20() : v20.mineTab === 'reminders' ? reminderSectionV20() : watchlistSectionV20();
    return `<div class="v20-watch-page">${pageHero('MY CENTER', '我的', '管理自選、手動目前持股與重要提醒。')}<div class="v20-mine-tabs" role="tablist"><button type="button" data-v20-mine="watchlist" class="${v20.mineTab === 'watchlist' ? 'active' : ''}">自選</button><button type="button" data-v20-mine="portfolio" class="${v20.mineTab === 'portfolio' ? 'active' : ''}">持股</button><button type="button" data-v20-mine="reminders" class="${v20.mineTab === 'reminders' ? 'active' : ''}">提醒</button></div>${section}${disclaimer()}</div>`;
  }

  async function ensureWatchDetails() {
    if (v20.watchLoading) return;
    const symbols = [...new Set(getWatchlist().map(item => String(item.symbol || '').trim().toUpperCase()))]
      .filter(symbol => /^[0-9]{4,6}[A-Z]?$/.test(symbol))
      .filter(symbol => !v20.detailCache.has(symbol) && !v20.watchAttempted.has(symbol))
      .slice(0, 20);
    if (!symbols.length) return;
    v20.watchLoading = true;
    symbols.forEach(symbol => v20.watchAttempted.add(symbol));
    for (let index = 0; index < symbols.length; index += 4) {
      const batch = symbols.slice(index, index + 4);
      const settled = await Promise.allSettled(batch.map(symbol => apiJson(`/stocks?symbol=${encodeURIComponent(symbol)}`)));
      settled.forEach((result, offset) => {
        const symbol = batch[offset];
        if (result.status !== 'fulfilled') {
          v20.watchAttempted.delete(symbol);
          v20.watchErrors.set(symbol, 'AI 分析更新失敗；保留既有資料，可稍後重試。');
          return;
        }
        v20.watchErrors.delete(symbol);
        v20.detailCache.set(symbol, result.value);
        writeCache(`stock:${symbol}`, result.value);
      });
      if (S.tab === 'watchlist') render();
    }
    v20.watchLoading = false;
  }

  function resetPortfolio(owner = '') {
    v20.portfolioOwner = owner;
    v20.portfolio = [];
    v20.portfolioLoaded = false;
    v20.portfolioLoading = false;
    v20.portfolioError = '';
    v20.portfolioMessage = '';
    v20.portfolioEditId = '';
    v20.portfolioDraft = null;
    v20.portfolioAttempted.clear();
    v20.portfolioErrors.clear();
  }

  async function ensurePortfolioDetails(positions = v20.portfolio) {
    const symbols = [...new Set(positions.map(item => String(item.symbol || '').trim().toUpperCase()))]
      .filter(symbol => /^[0-9A-Z]{2,12}$/.test(symbol))
      .filter(symbol => !portfolioStock(symbol).stock && !v20.portfolioAttempted.has(symbol))
      .slice(0, 40);
    if (!symbols.length) return;
    symbols.forEach(symbol => v20.portfolioAttempted.add(symbol));
    for (let index = 0; index < symbols.length; index += 4) {
      const batch = symbols.slice(index, index + 4);
      const settled = await Promise.allSettled(batch.map(symbol => apiJson(`/stocks?symbol=${encodeURIComponent(symbol)}`)));
      settled.forEach((result, offset) => {
        const symbol = batch[offset];
        if (result.status !== 'fulfilled') {
          v20.portfolioErrors.set(symbol, '行情或分析更新失敗；持股資料已保留。');
          return;
        }
        v20.portfolioErrors.delete(symbol);
        v20.detailCache.set(symbol, result.value);
        writeCache(`stock:${symbol}`, result.value);
      });
      if (S.tab === 'watchlist' && ['portfolio', 'reminders'].includes(v20.mineTab)) render();
    }
  }

  async function loadPortfolio(force = false) {
    const owner = sessionUserId();
    if (!owner || !S.session) {
      if (v20.portfolioOwner) resetPortfolio();
      return;
    }
    if (v20.portfolioOwner !== owner) resetPortfolio(owner);
    if (v20.portfolioLoading || (v20.portfolioLoaded && !force)) return;
    v20.portfolioLoading = true;
    v20.portfolioError = '';
    if (S.tab === 'watchlist') render();
    try {
      if (!await refreshSession() || sessionUserId() !== owner) throw new Error('登入已過期，請重新登入。');
      const rows = await coreSb(`/rest/v1/portfolio_positions?user_id=eq.${encodeURIComponent(owner)}&select=id,user_id,symbol,stock_name,quantity,average_cost,note,created_at,updated_at&order=updated_at.desc`);
      if (sessionUserId() !== owner) return;
      v20.portfolio = safeArray(rows);
      v20.portfolioLoaded = true;
      void ensurePortfolioDetails(v20.portfolio);
    } catch (error) {
      if (v20.portfolioOwner === owner) v20.portfolioError = `持股載入失敗：${error.message}`;
    } finally {
      if (v20.portfolioOwner === owner) v20.portfolioLoading = false;
      if (S.tab === 'watchlist') render();
    }
  }

  async function savePortfolio(event) {
    event.preventDefault();
    if (v20.portfolioSaving) return;
    const owner = sessionUserId();
    const symbol = String(q('#v20PortfolioSymbol')?.value || '').trim().toUpperCase();
    const localStock = S.stocks.find(item => String(item.symbol) === symbol);
    const stockName = String(q('#v20PortfolioName')?.value || localStock?.name || symbol).trim();
    const quantity = num(q('#v20PortfolioQuantity')?.value);
    const averageCost = num(q('#v20PortfolioCost')?.value);
    const note = String(q('#v20PortfolioNote')?.value || '').trim();
    v20.portfolioDraft = { symbol, stock_name: stockName, quantity: q('#v20PortfolioQuantity')?.value || '', average_cost: q('#v20PortfolioCost')?.value || '', note };
    v20.portfolioMessage = '';
    if (!owner || !S.session) v20.portfolioMessage = '請先登入。';
    else if (!/^[0-9A-Z]{2,12}$/.test(symbol)) v20.portfolioMessage = '股票代號需為 2～12 位英數字。';
    else if (!stockName || stockName.length > 120) v20.portfolioMessage = '請輸入有效股票名稱。';
    else if (!(quantity > 0)) v20.portfolioMessage = '目前股數必須大於 0。';
    else if (!(averageCost > 0)) v20.portfolioMessage = '平均成本必須大於 0。';
    else if (note.length > 1000) v20.portfolioMessage = '備註不可超過 1000 字。';
    if (v20.portfolioMessage) { render(); return; }
    v20.portfolioSaving = true;
    const submit = q('#v20PortfolioForm button[type="submit"]');
    if (submit) { submit.disabled = true; submit.textContent = '儲存中…'; }
    try {
      if (!await refreshSession() || sessionUserId() !== owner) throw new Error('登入已過期，請重新登入。');
      const body = { user_id: owner, symbol, stock_name: stockName, quantity, average_cost: averageCost, note };
      if (v20.portfolioEditId) {
        await coreSb(`/rest/v1/portfolio_positions?id=eq.${encodeURIComponent(v20.portfolioEditId)}&user_id=eq.${encodeURIComponent(owner)}`, { method: 'PATCH', headers: { Prefer: 'return=minimal' }, body });
      } else {
        await coreSb('/rest/v1/portfolio_positions?on_conflict=user_id,symbol', { method: 'POST', headers: { Prefer: 'resolution=merge-duplicates,return=minimal' }, body });
      }
      v20.portfolioEditId = '';
      v20.portfolioDraft = null;
      v20.portfolioMessage = '';
      await loadPortfolio(true);
    } catch (error) {
      v20.portfolioMessage = `儲存失敗：${error.message}`;
    } finally {
      v20.portfolioSaving = false;
      if (S.tab === 'watchlist') render();
    }
  }

  async function deletePortfolio(id) {
    const position = v20.portfolio.find(item => item.id === id);
    if (!position || !confirm(`確定刪除 ${position.stock_name || position.symbol} 的目前持股？`)) return;
    const owner = sessionUserId();
    try {
      if (!owner || !await refreshSession() || sessionUserId() !== owner) throw new Error('登入已過期，請重新登入。');
      await coreSb(`/rest/v1/portfolio_positions?id=eq.${encodeURIComponent(id)}&user_id=eq.${encodeURIComponent(owner)}`, { method: 'DELETE', headers: { Prefer: 'return=minimal' } });
      if (v20.portfolioEditId === id) v20.portfolioEditId = '';
      await loadPortfolio(true);
    } catch (error) {
      v20.portfolioError = `刪除失敗：${error.message}`;
      render();
    }
  }

  function analysisPageV20() {
    return `<div class="v20-analysis-page">${pageHero('AI ANALYSIS CENTER', 'AI 分析中心', 'AI 負責整理量化結果與說明原因，不會憑文字創造勝率。')}
      <section class="card v20-analysis-search"><h3>輸入股票代號</h3><p>查看短期與中期模型、風險、買點、失效條件及資料完整度。</p><div class="search-row"><input id="v20AnalysisSymbol" value="${esc(v20.analysisSymbol)}" inputmode="latin" maxlength="7" placeholder="例如 2330" aria-label="股票代號"><button id="v20Analyze" class="btn" type="button">開始分析</button></div>${v20.analysisMessage ? `<div class="notice">${esc(v20.analysisMessage)}</div>` : ''}</section>
      <section class="v20-section"><div class="v20-section-title"><div><span>HOW TO READ</span><h3>先看這三件事</h3></div></div><div class="v20-beginner-grid"><article class="card"><span>1</span><h3>為什麼值得注意</h3><p>看通過哪些硬性條件，以及量價、成長或法人是否有實質支撐。</p></article><article class="card"><span>2</span><h3>有什麼優點</h3><p>看機會分數、交易期望值與相對強度，不只看單一指標。</p></article><article class="card"><span>3</span><h3>有什麼風險</h3><p>看風險分數、停損及失效條件；資料不足時系統不會猜測。</p></article></div></section>${disclaimer()}</div>`;
  }

  const featureLabels = {
    technicalTrend: '技術趨勢', volumePrice: '量價結構', institutional: '法人籌碼', market: '市場環境',
    industry: '產業強度', news: '新聞事件', fundamentalSafety: '基本面安全', liquidity: '流動性',
    growthEarnings: '營收獲利', industryTrend: '產業趨勢', mediumTechnical: '中期趨勢',
    valuation: '估值狀態', financialSafety: '財務安全', completeness: '資料完整度', risk: '風險'
  };

  function factorGrid(scores) {
    const rows = Object.entries(scores || {}).filter(([, value]) => num(value?.value ?? value) != null);
    if (!rows.length) return '';
    return `<div class="v20-factor-grid">${rows.map(([key, value]) => `<div><small>${esc(featureLabels[key] || key)}</small><b>${displayNumber(value?.value ?? value, 0)}</b></div>`).join('')}</div>`;
  }

  function scoreExplanationGrid(signal) {
    const rows = safeArray(signal?.scoreExplanation);
    if (!rows.length) return factorGrid(signal?.featureScores);
    return `<h4>分數組成</h4><div class="v20-factor-grid">${rows.map(item => `<div><small>${esc(item.label || item.key)} · 權重 ${displayNumber(item.weight, 0)}%</small><b>${item.score == null ? '資料缺少（中性 50）' : `${displayNumber(item.score, 1)} 分`}</b><span>貢獻 ${displayNumber(item.contribution, 2)} 分</span></div>`).join('')}</div>`;
  }

  function gateSummary(signal) {
    const rows = safeArray(signal?.gateReasons);
    if (!rows.length) return '';
    const unresolved = rows.filter(item => item?.status !== 'pass');
    if (!unresolved.length) return '<div class="v20-inline-note"><b>推薦條件：</b>所有已知硬性條件均通過。</div>';
    return `<h4>未通過或待確認條件</h4><ul class="v20-detail-list">${unresolved.map(item => `<li><b>${esc(item.label || item.key)}：</b>${esc(item.reason || (item.status === 'fail' ? '未通過' : '資料不足，無法判定'))}</li>`).join('')}</ul>`;
  }

  function marketImpactSummary(signal) {
    const impact = signal?.marketImpact;
    if (!impact || typeof impact !== 'object') return '';
    const delta = num(impact.opportunityDeltaFromNeutral);
    return `<div class="v20-inline-note"><b>市場影響：</b>${esc(impact.featureLabel || '市場分項')}權重 ${displayNumber(impact.opportunityWeight, 0)}%，目前貢獻 ${displayNumber(impact.opportunityContribution, 2)} 分${delta == null ? '' : `，相對中性值${delta >= 0 ? '增加' : '減少'} ${displayNumber(Math.abs(delta), 2)} 分`}。${esc(impact.note || '')}</div>`;
  }

  function modelStateNotice(state) {
    if (!state || state.status === 'ready') return '';
    return `<div class="v20-inline-note"><b>${state.status === 'query_failed' ? '模型查詢失敗' : state.status === 'previous_date' ? '使用前一交易日模型' : '模型尚未完成'}：</b>${esc(state.reason || '尚未取得具體狀態。')}</div>`;
  }

  function detailResearchSections(detail) {
    const reference = detail?.legacyReference || {};
    const dimensions = reference.scoreDimensions || detail?.analysis?.scoreDimensions || {};
    const positives = safeArray(first(reference.positiveReasons, detail?.analysis?.positiveReasons));
    const negatives = safeArray(first(reference.negativeReasons, detail?.analysis?.opposingSignals));
    const risks = safeArray(first(reference.riskReasons, detail?.analysis?.riskReasons));
    const history = safeArray(first(reference.scoreHistory, detail?.analysis?.scoreHistory));
    const related = safeArray(detail?.relatedStocks);
    const sourceDates = Object.entries(detail?.sourceDates || {}).filter(([, value]) => value);
    return `${Object.keys(dimensions).length ? `<section><h3>技術、基本面與法人資料</h3><div class="card"><p class="muted">以下是既有可驗證資料面向，v20 短中期總分仍各自獨立計算。</p>${factorGrid(dimensions)}</div></section>` : ''}
      ${positives.length || negatives.length || risks.length ? `<section><h3>理由與反對訊號</h3><div class="card">${positives.length ? `<h4>值得注意</h4><ul class="v20-detail-list">${positives.slice(0, 6).map(item => `<li>${esc(item)}</li>`).join('')}</ul>` : ''}${negatives.length ? `<h4>反對訊號</h4><ul class="v20-detail-list">${negatives.slice(0, 6).map(item => `<li>${esc(item)}</li>`).join('')}</ul>` : ''}${risks.length ? `<h4>風險提醒</h4><ul class="v20-detail-list v20-risk-text">${risks.slice(0, 6).map(item => `<li>${esc(item)}</li>`).join('')}</ul>` : ''}</div></section>` : ''}
      ${history.length ? `<section><h3>分數歷史</h3><div class="v20-history">${history.slice(0, 20).map(item => `<div><small>${esc(first(item.date, item.scoreDate, '日期待補'))}</small><b>${displayNumber(first(item.score, item.value), 0)}</b></div>`).join('')}</div></section>` : ''}
      ${related.length ? `<section><h3>相關股票</h3><div class="card v20-related">${related.slice(0, 6).map(item => `<button type="button" data-v20-detail="${esc(item.symbol)}"><span><b>${esc(item.name || item.symbol)}</b><small>${esc(item.symbol)} · ${esc(first(item.industry, item.market, '資料待補'))}</small></span><strong>${displayNumber(first(item.opportunityScore, item.aiScore?.value, item.score), 0)}</strong></button>`).join('')}</div></section>` : ''}
      ${sourceDates.length ? `<section><h3>資料來源日期</h3><div class="card v20-factor-grid">${sourceDates.map(([key, value]) => `<div><small>${esc(key)}</small><b>${esc(value)}</b></div>`).join('')}</div></section>` : ''}`;
  }

  function signalSection(signals, model, modelState = null) {
    const label = model === 'short' ? '短期模型' : '中期模型';
    if (!signals.length) return `<section><h3>${label}</h3><div class="card v20-empty"><b>${modelState?.status === 'query_failed' ? '模型查詢失敗' : '模型訊號尚未產生'}</b><p>${esc(modelState?.reason || `${label}工作尚未完成；行情、基本面完整度與模型預測狀態是不同項目。`)}</p></div></section>`;
    return `<section><h3>${label}</h3>${modelStateNotice(modelState)}<div class="v20-signal-grid">${signals.map(signal => {
      const forecast = forecastFor(signal);
      const prediction = predictionFor(signal, forecast);
      const range = forecast.returnRange || {};
      const invalidations = safeArray(signal.invalidationConditions);
      const reasons = safeArray(signal.reasons);
      const risks = safeArray(signal.risks);
      const forecastBlock = prediction.publicForecast
        ? `<div class="v20-forecast-row"><div><small>上漲機率</small><b>${probability(forecast.upProbability)}</b></div><div><small>預估淨報酬</small><b>${displayPercent(forecast.expectedNetReturn)}</b></div><div><small>信心／完整度</small><b>${probability(signal.confidence)}／${probability(signal.completeness)}</b></div></div>`
        : `<div class="v20-inline-note"><b>預測尚未公開：</b>${esc(prediction.reason || '尚未完成 Walk-forward 校準。')}目前仍可參考機會分數、風險、因子與交易條件。</div><div class="v20-forecast-row"><div><small>預測狀態</small><b>尚未校準</b></div><div><small>模型信心</small><b>${probability(signal.confidence)}</b></div><div><small>資料完整度</small><b>${probability(signal.completeness)}</b></div></div>`;
      const calibratedRanges = prediction.publicForecast ? `<span>悲觀／中位／樂觀 <b>${displayPercent(range.p10)}／${displayPercent(range.p50)}／${displayPercent(range.p90)}</b></span><span>MFE／MAE <b>${displayPercent(forecast.averageMfe)}／${displayPercent(forecast.averageMae)}</b></span>` : '';
      return `<article class="card v20-signal-card"><div class="head"><div><span class="tag info">${signal.horizon} 日 · ${esc(first(signal.dataDate, '日期待補'))}</span><h3>${esc(strategyLabel(signal.strategy))}</h3></div><div class="v20-card-score"><small>機會／風險</small><strong>${displayNumber(signal.opportunityScore, 0)}<i>／${displayNumber(signal.riskScore, 0)}</i></strong></div></div>${forecastBlock}${scoreExplanationGrid(signal)}${marketImpactSummary(signal)}${reasons.length ? `<h4>為什麼值得注意</h4><ul class="v20-detail-list">${reasons.slice(0, 5).map(item => `<li>${esc(localizeStrategyText(item))}</li>`).join('')}</ul>` : `<p><b>為什麼值得注意：</b>${esc(localizeStrategyText(first(signal.summary, '尚未整理出已驗證的正面原因')))}</p>`}${risks.length ? `<h4>主要風險</h4><ul class="v20-detail-list v20-risk-text">${risks.slice(0, 6).map(item => `<li>${esc(localizeStrategyText(item))}</li>`).join('')}</ul>` : '<p class="v20-risk-text"><b>主要風險：</b>尚未發現額外風險，但仍須遵守停損與失效條件。</p>'}${gateSummary(signal)}<div class="v20-plan-grid">${calibratedRanges}<span>布局區 <b>${displayNumber(signal.tradePlan?.entryLow, 2)}–${displayNumber(signal.tradePlan?.entryHigh, 2)}</b></span><span>突破確認價 <b>${displayNumber(signal.tradePlan?.breakoutPrice, 2)}</b></span><span>不追價價格 <b>${displayNumber(signal.tradePlan?.noChasePrice, 2)}</b></span><span>停損 <b>${displayNumber(signal.tradePlan?.stopLoss, 2)}</b></span><span>第一／第二停利 <b>${displayNumber(signal.tradePlan?.takeProfit1, 2)}／${displayNumber(signal.tradePlan?.takeProfit2, 2)}</b></span><span>風報比／持有期 <b>${displayNumber(signal.tradePlan?.riskRewardRatio, 2)}／${displayNumber(signal.tradePlan?.recommendedHoldingDays, 0)} 日</b></span></div>${invalidations.length ? `<h4>失效條件</h4><ul class="v20-detail-list">${invalidations.slice(0, 6).map(item => `<li>${esc(localizeStrategyText(item))}</li>`).join('')}</ul>` : ''}<div class="v20-action">${esc(signal.recommendedAction || '資料不足')}</div></article>`;
    }).join('')}</div></section>`;
  }

  function positionCalculator(detail) {
    const signal = [...safeArray(detail?.short), ...safeArray(detail?.medium)].find(item => num(item.tradePlan?.stopLoss) != null);
    const entry = first(signal?.tradePlan?.entryLow, detail?.quote?.close, '');
    const stop = first(signal?.tradePlan?.stopLoss, '');
    return `<section><h3>一次性部位試算</h3><div class="card v20-calculator"><p>只在目前畫面計算，不會儲存資金、成本或交易紀錄。</p><div class="v20-calculator-grid"><label>試算資金<input id="v20Capital" type="number" inputmode="decimal" min="0" placeholder="例如 1000000"></label><label>單筆風險<select id="v20RiskRatio"><option value="0.005">0.5%</option><option value="0.0075">0.75%</option><option value="0.01">1%</option></select></label><label>試算買進價<input id="v20Entry" type="number" inputmode="decimal" min="0" step="0.01" value="${esc(entry)}"></label><label>停損價<input id="v20Stop" type="number" inputmode="decimal" min="0" step="0.01" value="${esc(stop)}"></label></div><button id="v20Calculate" type="button" class="btn v20-full">計算可承擔股數</button><output id="v20PositionResult" class="v20-calculator-result">輸入資金後開始試算</output></div></section>`;
  }

  function detailHtml(symbol, detail, loading = false, error = '') {
    const local = S.stocks.find(stock => String(stock.symbol) === String(symbol)) || {};
    const stock = detail?.stock || detail?.quote || local;
    const name = first(stock?.name, detail?.short?.[0]?.name, detail?.medium?.[0]?.name, symbol);
    return `<div class="modal"><div class="sheet v20-detail-sheet"><button class="sheet-close" type="button" aria-label="關閉">×</button><div class="v20-detail-head"><div><span class="v20-eyebrow">V20 QUANT ANALYSIS</span><h2>${esc(name)} <small>${esc(symbol)}</small></h2><p>${esc(first(stock?.market, stock?.industry, '市場資料待補'))} · 資料日期 ${esc(first(detail?.dataDate, stock?.priceDate, S.date, '待補'))}</p></div><button class="btn secondary" type="button" data-watch="${esc(symbol)}">${isWatched(symbol) ? '✓ 已自選' : '＋ 自選'}</button></div>
      ${statusBanner(detail || {}, loading ? 'refreshing' : detail?.dataState, error)}
      <div class="v20-quote"><div><small>最新盤後價格 · ${esc(first(detail?.tradeDate, stock?.priceDate, '日期待補'))}</small><strong>${displayNumber(first(stock?.close, stock?.price), 2)}</strong></div><div><small>當日漲跌</small><b class="${num(stock?.change) > 0 ? 'up' : num(stock?.change) < 0 ? 'down' : 'muted'}">${displayPercent(stock?.change, 2)}</b></div><div><small>資料完整度</small><b>${probability(detail?.completeness)}</b></div></div>
      <div class="card v20-factor-grid"><div><small>交易日期</small><b>${esc(first(detail?.tradeDate, '待補'))}</b></div><div><small>分析資料日期</small><b>${esc(first(detail?.analysisDataDate, '待補'))}</b></div><div><small>最新新聞發布</small><b>${esc(first(detail?.newsPublishedAt?.slice?.(0, 16), '待補'))}</b></div><div><small>分析產生時間</small><b>${esc(first(detail?.analysisGeneratedAt?.slice?.(0, 16), '待補'))}</b></div></div>
      ${signalSection(safeArray(detail?.short), 'short', detail?.modelStates?.short)}${signalSection(safeArray(detail?.medium), 'medium', detail?.modelStates?.medium)}${detailResearchSections(detail)}${positionCalculator(detail)}
      ${safeArray(detail?.news).length ? `<section><h3>重要新聞與公告</h3><div class="card v20-news-list">${detail.news.slice(0, 8).map(item => `<article><div><b>${esc(item.title || '未命名公告')}</b><small>${esc(first(item.source, '公開來源'))} · ${esc(first(item.eventDate, item.publishedAt?.slice?.(0, 10), '日期待補'))}</small></div></article>`).join('')}</div></section>` : ''}
      ${disclaimer()}</div></div>`;
  }

  function bindPositionCalculator() {
    q('#v20Calculate', modalRoot)?.addEventListener('click', () => {
      const capital = num(q('#v20Capital', modalRoot)?.value);
      const ratio = num(q('#v20RiskRatio', modalRoot)?.value);
      const entry = num(q('#v20Entry', modalRoot)?.value);
      const stop = num(q('#v20Stop', modalRoot)?.value);
      const output = q('#v20PositionResult', modalRoot);
      if (!output) return;
      if (!(capital > 0) || !(ratio > 0) || !(entry > stop) || !(stop > 0)) {
        output.textContent = '請輸入有效資金，且買進價必須高於停損價。';
        return;
      }
      const riskAmount = capital * ratio;
      const shares = Math.floor(riskAmount / (entry - stop));
      const lots = Math.floor(shares / 1000);
      output.innerHTML = `最大風險金額 <b>${displayNumber(riskAmount, 0)} 元</b> · 試算股數 <b>${displayNumber(shares, 0)} 股</b>${lots ? `（約 ${lots} 張）` : ''}`;
    });
  }

  function paintDetail(symbol, detail, loading, error = '') {
    if (S.detailSymbol !== symbol) return;
    const scroll = q('.sheet', modalRoot)?.scrollTop || 0;
    modalRoot.innerHTML = detailHtml(symbol, detail, loading, error);
    bindModal();
    bindPositionCalculator();
    const sheet = q('.sheet', modalRoot); if (sheet) sheet.scrollTop = scroll;
  }

  async function openV20Detail(symbol) {
    symbol = String(symbol || '').trim().toUpperCase();
    if (!/^[0-9]{4,6}[A-Z]?$/.test(symbol)) return;
    S.detailSymbol = symbol;
    const cached = v20.detailCache.get(symbol) || readCache(`stock:${symbol}`);
    paintDetail(symbol, cached, true);
    try {
      const detail = await apiJson(`/stocks?symbol=${encodeURIComponent(symbol)}`);
      v20.detailCache.set(symbol, detail);
      writeCache(`stock:${symbol}`, detail);
      paintDetail(symbol, detail, false);
    } catch (error) {
      paintDetail(symbol, cached, false, error.message || '更新失敗');
    }
  }

  function queryFor(model, page, cursor = '') {
    const params = new URLSearchParams({ model, horizon: String(page.horizon), limit: cursor ? '20' : '10', sort: page.sort });
    if (page.market !== 'all') params.set('market', page.market);
    if (page.industry) params.set('industry', page.industry);
    if (page.search) params.set('search', page.search);
    if (cursor) params.set('cursor', cursor);
    return `/rankings?${params}`;
  }

  async function loadRankings(model, append = false) {
    const page = v20.pages[model];
    if (page.loading) return;
    page.loading = true;
    page.phase = page.items.length ? 'refreshing' : page.phase;
    page.error = '';
    const requestId = ++page.requestId;
    if (S.tab === model) render();
    try {
      const payload = await apiJson(queryFor(model, page, append ? page.nextCursor : ''));
      if (requestId !== page.requestId) return;
      const existing = append ? page.items : [];
      const bySymbol = new Map(existing.map(item => [item.symbol, item]));
      safeArray(payload.items).forEach(item => bySymbol.set(item.symbol, item));
      page.items = [...bySymbol.values()];
      page.nextCursor = payload.nextCursor || null;
      page.totalEstimate = payload.totalEstimate || page.items.length;
      page.dataDate = payload.dataDate || page.dataDate;
      page.completeness = payload.completeness || 0;
      page.dataCompleteness = payload.dataCompleteness || page.completeness;
      page.publicationPhase = payload.publicationPhase || payload.dataState || 'partial';
      page.enrichmentPending = payload.enrichmentPending || 0;
      page.degradedSources = safeArray(payload.degradedSources);
      page.phase = payload.dataState || 'partial';
      page.loaded = true;
      if (!append) writeCache(`rankings:${model}`, payload);
    } catch (error) {
      if (requestId !== page.requestId) return;
      page.phase = 'error';
      page.error = error.name === 'AbortError' ? '更新逾時，保留目前資料。' : error.message;
    } finally {
      if (requestId === page.requestId) page.loading = false;
      if (S.tab === model) render();
    }
  }

  function ensureRankings(model) {
    const page = v20.pages[model];
    if (!page.loaded && !page.loading) void loadRankings(model);
  }

  async function loadHome() {
    v20.homePhase = v20.home ? 'refreshing' : 'refreshing';
    if (S.tab === 'home') render();
    try {
      const payload = await apiJson('/home');
      v20.home = payload;
      v20.homePhase = payload.dataState || 'partial';
      v20.homeError = '';
      const atomicReport = unwrapDailyReport(payload.dailyReport);
      if (atomicReport && dateKey(atomicReport.meta.dataDate) === dateKey(payload.dataDate)) {
        v20.dailyReport = atomicReport;
        v20.dailyPhase = atomicReport.meta.publicationPhase || 'base_ready';
        v20.dailyError = '';
        try { localStorage.setItem('twss-v19-daily-report-cache', JSON.stringify(payload.dailyReport)); } catch { /* optional */ }
      }
      writeCache('home', payload);
    } catch (error) {
      v20.homePhase = v20.home ? 'cache' : 'error';
      v20.homeError = error.name === 'AbortError' ? '背景更新逾時，保留快取資料。' : error.message;
    }
    if (S.tab === 'home') render();
  }

  async function loadDailyReport() {
    v20.dailyPhase = v20.dailyReport ? 'refreshing' : 'refreshing';
    if (S.tab === 'home') render();
    try {
      const response = await fetch('/data/daily-report.json', { cache: 'force-cache', headers: { accept: 'application/json' } });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const raw = await response.json();
      const wrapped = unwrapDailyReport(raw);
      if (!wrapped) throw new Error('daily_report_invalid');
      const expectedDate = dateKey(v20.home?.dataDate);
      const currentDate = dateKey(v20.dailyReport?.meta?.dataDate);
      if (expectedDate && currentDate === expectedDate) return;
      wrapped.meta = {
        ...wrapped.meta,
        publicationPhase: 'cached',
        updateStatus: 'cached',
        cachedFallback: true,
        expectedDataDate: expectedDate || null,
      };
      v20.dailyReport = wrapped;
      v20.dailyPhase = 'cache';
      v20.dailyError = '';
      try { localStorage.setItem('twss-v19-daily-report-cache', JSON.stringify(raw)); } catch { /* optional */ }
    } catch (error) {
      v20.dailyPhase = v20.dailyReport ? 'cache' : 'error';
      v20.dailyError = error.message || '更新失敗';
    }
    if (S.tab === 'home') render();
  }

  const legacyBind = bind;
  bind = function bindV20() {
    legacyBind();
    enforceDarkOnly();
    qa('[data-v20-mine]').forEach(button => button.onclick = () => {
      v20.mineTab = button.dataset.v20Mine;
      v20.portfolioMessage = '';
      v20.portfolioEditId = '';
      v20.portfolioDraft = null;
      render();
      if (['portfolio', 'reminders'].includes(v20.mineTab)) void loadPortfolio();
    });
    q('#v20PortfolioLogin')?.addEventListener('click', () => q('#accountBtn')?.click());
    q('#v20PortfolioForm')?.addEventListener('submit', savePortfolio);
    q('#v20PortfolioCancel')?.addEventListener('click', () => { v20.portfolioEditId = ''; v20.portfolioDraft = null; v20.portfolioMessage = ''; render(); });
    q('#v20PortfolioSymbol')?.addEventListener('change', event => {
      const symbol = String(event.target.value || '').trim().toUpperCase();
      event.target.value = symbol;
      const nameInput = q('#v20PortfolioName');
      const stock = S.stocks.find(item => String(item.symbol) === symbol);
      if (nameInput && !nameInput.value.trim() && stock?.name) nameInput.value = stock.name;
    });
    qa('[data-portfolio-edit]').forEach(button => button.onclick = () => { v20.portfolioEditId = button.dataset.portfolioEdit; v20.portfolioDraft = null; v20.portfolioMessage = ''; render(); q('#v20PortfolioForm')?.scrollIntoView({ behavior: 'smooth', block: 'start' }); });
    qa('[data-portfolio-delete]').forEach(button => button.onclick = () => void deletePortfolio(button.dataset.portfolioDelete));
    qa('[data-tab-jump]').forEach(button => button.onclick = () => navigateToTab(button.dataset.tabJump));
    q('#v20NewsMore')?.addEventListener('click', () => { v20.newsVisible += 10; render(); });
    qa('[data-v20-detail]').forEach(element => element.onclick = event => {
      if (event.target.closest('[data-watch]')) return;
      event.stopPropagation(); openV20Detail(element.dataset.v20Detail);
    });
    const model = S.tab === 'short' || S.tab === 'medium' ? S.tab : null;
    if (model) {
      const page = v20.pages[model];
      q('#v20Horizon')?.addEventListener('change', event => { page.horizon = Number(event.target.value); page.nextCursor = null; page.loaded = false; loadRankings(model); });
      q('#v20Market')?.addEventListener('change', event => { page.market = event.target.value; page.nextCursor = null; page.loaded = false; loadRankings(model); });
      q('#v20Industry')?.addEventListener('change', event => { page.industry = event.target.value.trim(); page.nextCursor = null; page.loaded = false; loadRankings(model); });
      q('#v20Industry')?.addEventListener('keydown', event => { if (event.key === 'Enter') { page.industry = event.target.value.trim(); page.nextCursor = null; page.loaded = false; loadRankings(model); } });
      q('#v20Sort')?.addEventListener('change', event => { page.sort = event.target.value; page.nextCursor = null; page.loaded = false; loadRankings(model); });
      const search = () => { page.search = q('#v20Search')?.value.trim() || ''; page.nextCursor = null; page.loaded = false; loadRankings(model); };
      q('#v20SearchBtn')?.addEventListener('click', search);
      q('#v20Search')?.addEventListener('keydown', event => { if (event.key === 'Enter') search(); });
      q('#v20LoadMore')?.addEventListener('click', () => loadRankings(model, true));
    }
    if (S.tab === 'watchlist') {
      void ensureWatchDetails();
      if (['portfolio', 'reminders'].includes(v20.mineTab)) void loadPortfolio();
    }
    q('#v20Analyze')?.addEventListener('click', () => {
      const symbol = q('#v20AnalysisSymbol')?.value.trim().toUpperCase() || '';
      v20.analysisSymbol = symbol;
      if (!/^[0-9]{4,6}[A-Z]?$/.test(symbol)) { v20.analysisMessage = '請輸入有效的台股代號，例如 2330。'; render(); return; }
      v20.analysisMessage = ''; openV20Detail(symbol);
    });
    q('#v20AnalysisSymbol')?.addEventListener('keydown', event => { if (event.key === 'Enter') q('#v20Analyze')?.click(); });
  };

  navigateToTab = function navigateV20(tab) {
    const aliases = { opportunities: 'short', mine: 'watchlist', watch: 'watchlist' };
    const next = aliases[tab] || tab;
    if (!VALID_TABS.has(next)) return;
    S.tab = next;
    render();
    resetPageScroll();
    if (next === 'short' || next === 'medium') ensureRankings(next);
    if (next === 'watchlist') {
      void ensureWatchDetails();
      if (['portfolio', 'reminders'].includes(v20.mineTab)) void loadPortfolio();
    }
  };

  render = function renderV20() {
    const aliases = { opportunities: 'short', mine: 'watchlist', watch: 'watchlist' };
    S.tab = aliases[S.tab] || S.tab;
    if (!VALID_TABS.has(S.tab)) S.tab = 'home';
    qa('.bottom-nav button').forEach(button => {
      const active = button.dataset.tab === S.tab;
      button.classList.toggle('active', active);
      if (active) button.setAttribute('aria-current', 'page'); else button.removeAttribute('aria-current');
    });
    updateAccountUi();
    updateMarketHeader();
    app.innerHTML = S.tab === 'home' ? homePageV20()
      : S.tab === 'short' ? rankingPageV20('short')
        : S.tab === 'medium' ? rankingPageV20('medium')
          : S.tab === 'watchlist' ? watchlistPageV20()
            : analysisPageV20();
    bind();
  };

  openDetail = openV20Detail;
  enforceDarkOnly();
  render();
  void loadHome();
  void loadDailyReport();
})();
