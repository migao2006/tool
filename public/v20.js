(() => {
  'use strict';

  // The v20 shell loads summary/read-model APIs first. Legacy all-market
  // fundamentals are deferred; individual detail is fetched on demand.
  globalThis.twssV20Active = true;

  const API = '/api/v20';
  // Deliberately do not reuse pre-immutable v20.1 cache entries, which may
  // contain mutable v19 enrichment from an older frontend release.
  const CACHE_PREFIX = 'twss-v20.1-immutable-cache:';
  const VALID_TABS = new Set(['home', 'short', 'medium', 'watchlist', 'validation']);
  const HORIZONS = { short: [2, 3, 5, 10], medium: [10, 20, 40] };
  const DEFAULT_HORIZON = { short: 5, medium: 20 };
  const RANKING_SORTS = new Set(['net_opportunity_desc', 'score_desc', 'risk_asc', 'change_desc']);
  const MIN_VALIDATION_SAMPLES = 100;
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
  const supportedPayload = payload => String(payload?.version || '') === '20.1';
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
      return supportedPayload(parsed?.payload) ? parsed.payload : null;
    } catch { return null; }
  }

  function writeCache(key, payload) {
    if (!supportedPayload(payload)) return;
    try { localStorage.setItem(`${CACHE_PREFIX}${key}`, JSON.stringify({ savedAt: new Date().toISOString(), payload })); } catch { /* cache is optional */ }
  }

  function unwrapDailyReport(value) {
    const payload = value?.data && typeof value.data === 'object' ? value.data : value;
    if (!payload || typeof payload !== 'object') return null;
    return { meta: payload, report: payload.report && typeof payload.report === 'object' ? payload.report : payload };
  }

  function samePublication(left, right) {
    const leftRun = Number(left?.runId);
    const rightRun = Number(right?.runId);
    const leftKey = String(left?.publicationKey || '');
    const rightKey = String(right?.publicationKey || '');
    const leftHash = String(left?.contentHash || '');
    const rightHash = String(right?.contentHash || '');
    return Number.isInteger(leftRun) && leftRun > 0 && leftRun === rightRun
      && /^[0-9a-f]{64}$/i.test(leftKey) && leftKey === rightKey
      && /^[0-9a-f]{64}$/i.test(leftHash) && leftHash === rightHash
      && dateKey(left?.dataDate) === dateKey(right?.dataDate);
  }

  function rankingState(model) {
    const cachedCandidate = readCache(`rankings:${model}`);
    const cached = samePublication(cachedCandidate, cachedHome) ? cachedCandidate : null;
    const cachedHorizon = Number(cached?.horizon);
    const cachedSort = String(cached?.sort || '');
    const horizon = HORIZONS[model].includes(cachedHorizon) ? cachedHorizon : DEFAULT_HORIZON[model];
    return {
      items: publicModelRows(cached?.items, model)
        .filter(row => publicHorizon(row) === horizon),
      nextCursor: cached?.nextCursor || null,
      totalEstimate: cached?.totalEstimate || 0,
      dataDate: cached?.dataDate || null,
      runId: cached?.runId || null,
      publicationKey: cached?.publicationKey || null,
      contentHash: cached?.contentHash || null,
      completeness: cached?.completeness || 0,
      dataCompleteness: cached?.dataCompleteness || cached?.completeness || 0,
      publicationPhase: cached?.publicationPhase || (cached ? 'cached' : 'refreshing'),
      enrichmentPending: cached?.enrichmentPending || 0,
      degradedSources: safeArray(cached?.degradedSources),
      phase: cached ? 'cache' : 'refreshing',
      loading: false,
      loaded: false,
      error: '',
      horizon,
      market: cached?.filters?.market || 'all',
      industry: cached?.filters?.industry || '',
      sort: RANKING_SORTS.has(cachedSort) ? cachedSort : 'net_opportunity_desc',
      search: cached?.filters?.search || '',
      requestId: 0
    };
  }

  const cachedHome = readCache('home');
  const cachedDailyReportCandidate = unwrapDailyReport(cachedHome?.dailyReport);
  const cachedDailyReport = samePublication(cachedDailyReportCandidate?.meta, cachedHome)
    ? cachedDailyReportCandidate
    : null;
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
    newsVisible: 5,
    analysisSymbol: '',
    analysisMessage: '',
    validation: null,
    validationModel: 'short',
    validationHorizon: DEFAULT_HORIZON.short,
    validationLoading: false,
    validationLoaded: false,
    validationError: ''
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

  const globalIndicatorDefinitions = [[['nasdaq'], 'NASDAQ'], [['sp500'], 'S&P 500'], [['sox'], 'SOX'], [['tsmAdr'], '台積電 ADR'], [['nvidia', 'nvda'], 'NVIDIA'], [['vix'], 'VIX'], [['us10y', 'usTreasury'], '美債 10Y'], [['usdTwd', 'twdUsd'], 'USD/TWD']];

  function usableMarketValue(value) {
    return num(marketValue(value)) != null;
  }

  function visibleDegradedSources(sources, market = {}) {
    const resolved = new Set([
      usableMarketValue(market.taiex) && 'taiex_official_index',
      usableMarketValue(market.tpex) && 'tpex_official_index',
      usableMarketValue(market.txFutures) && 'tx_futures',
    ].filter(Boolean));
    const context = market.globalContext || {};
    const resolvedGlobal = globalIndicatorDefinitions.filter(([keys]) => keys.some(key => usableMarketValue(context[key])));
    resolvedGlobal.forEach(([keys]) => keys.forEach(key => resolved.add(`global_${key}`)));
    if (resolvedGlobal.length === globalIndicatorDefinitions.length) {
      resolved.add('international_context');
      resolved.add('global_market_context');
    }
    return [...new Set(safeArray(sources))].filter(source => !resolved.has(source));
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

  function calibrationSampleCount(row, forecast = forecastFor(row)) {
    return num(first(forecast?.sampleSize, forecast?.sampleCount, row?.calibrationSampleCount, row?.sampleCount));
  }

  function validatedForecast(row, forecast = forecastFor(row)) {
    const prediction = predictionFor(row, forecast);
    const samples = calibrationSampleCount(row, forecast);
    return { prediction, samples, publishable: prediction.publicForecast === true && samples >= MIN_VALIDATION_SAMPLES };
  }

  function hiddenForecastReason(validation) {
    if (validation.samples == null) return '校準樣本數尚未隨結果公開，無法驗證最低門檻。';
    if (validation.samples < MIN_VALIDATION_SAMPLES) return `有效樣本 ${displayNumber(validation.samples, 0)} 筆，未達 ${MIN_VALIDATION_SAMPLES} 筆。`;
    return validation.prediction.reason || '尚未完成 Walk-forward 校準。';
  }

  function costAdjustedValue(row) {
    return num(first(row?.netOpportunityScore, row?.netOpportunityValue, row?.costAdjustedScore, row?.costAdjustedOpportunity));
  }

  function estimatedCost(row, forecast = forecastFor(row)) {
    return num(first(row?.executionCosts?.totalPct, row?.estimatedTotalCostPct, row?.estimatedCostPct, row?.transactionCostPct, forecast?.estimatedTotalCostPct, forecast?.estimatedCostPct));
  }

  function publicHorizon(row) {
    return num(first(row?.horizon, row?.horizonDays, row?.horizon_days));
  }

  function publicModelRows(rows, model) {
    return safeArray(rows).filter(row => {
      const horizon = publicHorizon(row);
      const rowModel = first(row?.model, row?.modelKey, row?.model_key);
      const researchOnly = row?.researchOnly === true || row?.research_only === true;
      const publicVisible = first(row?.publicVisible, row?.public_visible);
      return row && typeof row === 'object'
        && !researchOnly
        && publicVisible !== false
        && (rowModel == null || rowModel === model)
        && HORIZONS[model].includes(horizon);
    });
  }

  function cardConditions(row) {
    const risks = safeArray(row?.risks);
    const invalidations = safeArray(row?.invalidationConditions);
    if (!risks.length && !invalidations.length) return '<div class="v20-inline-note"><b>風險／失效：</b>條件資料待補，不自行推測。</div>';
    return `<div class="v20-card-conditions">${risks[0] ? `<p><b>風險：</b>${esc(localizeStrategyText(risks[0]))}</p>` : ''}${invalidations[0] ? `<p><b>失效：</b>${esc(localizeStrategyText(invalidations[0]))}</p>` : ''}</div>`;
  }

  function modelCard(row) {
    const forecast = forecastFor(row);
    const validation = validatedForecast(row, forecast);
    const reference = row.legacyReference === true;
    const rank = first(row.rank, row.rankPosition, row.rank_position, '—');
    const netValue = costAdjustedValue(row);
    const cost = estimatedCost(row, forecast);
    return `<article class="card v20-model-card ${reference ? 'reference' : ''}" data-v20-detail="${esc(row.symbol)}">
      <div class="v20-card-head"><span class="v20-rank">${esc(rank)}</span><div class="v20-card-name"><b>${esc(row.name || row.symbol)}</b><small>${esc(row.symbol)} · ${esc(first(row.market, row.group, '市場待補'))}</small></div><div class="v20-card-score"><small>${reference ? '舊資料參考' : '機會分數'}</small><strong>${reference ? '—' : displayNumber(row.opportunityScore, 0)}</strong></div></div>
      <p class="v20-summary">${esc(localizeStrategyText(first(row.summary, safeArray(row.reasons)[0], reference ? 'v20 模型建立中，暫不提供推測分數。' : '分析原因待補')))}</p>
      <div class="v20-chip-row"><span>${esc(strategyLabel(row.strategy))}</span><span>風險 ${displayNumber(row.riskScore, 0)}</span><span>資料完整度 ${probability(row.completeness)}</span><span>資料 ${esc(first(row.dataDate, '日期待補'))}</span></div>
      <div class="v20-forecast-row"><div><small>成本後機會值</small><b>${netValue == null ? '尚未產生' : displayNumber(netValue, 1)}</b></div><div><small>預估交易成本</small><b>${cost == null ? '尚未產生' : displayPercent(-Math.abs(cost), 3)}</b></div><div><small>校準狀態</small><b>${validation.publishable ? `已驗證 · ${displayNumber(validation.samples, 0)} 筆` : validation.samples == null ? '樣本數待補' : `累積中 · ${displayNumber(validation.samples, 0)} 筆`}</b></div></div>
      ${validation.publishable ? `<div class="v20-inline-note"><b>歷史驗證：</b>${row.horizon} 日成本後正報酬比例 ${probability(forecast.upProbability)}；這是相似條件歷史結果，不是未來保證。</div>` : `<div class="v20-inline-note"><b>不公開機率：</b>${esc(hiddenForecastReason(validation))}</div>`}
      ${cardConditions(row)}
      <div class="row v20-card-actions"><button class="btn secondary grow" type="button" data-watch="${esc(row.symbol)}">${isWatched(row.symbol) ? '✓ 已自選' : '＋ 加入自選'}</button><button class="btn grow" type="button" data-v20-detail="${esc(row.symbol)}">查看分析</button></div>
    </article>`;
  }

  function compactList(rows, model) {
    const visible = publicModelRows(rows, model);
    if (!visible.length) return '<div class="card v20-empty"><b>模型資料正在建立</b><p>先顯示頁面，完成校準後會自動補上排行，不會使用猜測數字。</p></div>';
    return `<div class="v20-top-list">${visible.slice(0, 5).map(row => `<button type="button" data-v20-detail="${esc(row.symbol)}"><span>${esc(first(row.rank, row.rankPosition, row.rank_position, '—'))}</span><div><b>${esc(row.name || row.symbol)}</b><small>${esc(row.symbol)} · ${esc(first(strategyLabel(row.strategy), row.industry, '資料待補'))}</small></div><strong>${row.legacyReference ? '—' : displayNumber(row.opportunityScore, 0)}</strong><i>›</i></button>`).join('')}</div><button class="v20-more-link" type="button" data-tab-jump="${model}">查看完整${model === 'short' ? '短期' : '中期'}排行 →</button>`;
  }

  function globalStrip(market) {
    const context = market?.globalContext || {};
    const rows = globalIndicatorDefinitions.flatMap(([keys, label]) => {
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
    const degradedSources = visibleDegradedSources(meta.degradedSources, v20.home?.market);
    if (!wrapped) return `<section class="v20-section"><div class="v20-section-title"><div><span>DAILY AI BRIEF</span><h3>AI 每日報告</h3></div></div><div class="card v20-empty">${v20.dailyPhase === 'refreshing' ? '<span class="spinner"></span> 正在背景讀取最近一次報告，首頁其他內容可先使用。' : '每日報告更新失敗，保留其他已載入內容。'}</div></section>`;
    return `<section class="v20-section"><div class="v20-section-title"><div><span>DAILY AI BRIEF</span><h3>AI 每日報告</h3></div><small>${esc(meta.dataDate || '日期待補')}</small></div><article class="card v20-daily-report">${statusBanner({ dataState: degradedSources.length ? meta.updateStatus || meta.dataState : 'complete', dataDate: meta.dataDate, publicationPhase: meta.publicationPhase, enrichmentPending: meta.enrichmentPending, degradedSources }, v20.dailyPhase, v20.dailyError)}<p class="v20-daily-lead">${esc(first(report.oneLine, report.todayInOneSentence, '今日市場結論待補'))}</p><div class="v20-daily-grid"><div><small>市場強弱</small><b>${esc(first(strength.level, strength.label, '資料不足'))}</b><p>${esc(first(strength.explanation, '等待市場廣度資料補齊。'))}</p></div><div><small>法人方向</small><b>${esc(first(institutional.direction, institutional.label, '資料不足'))}</b><p>${esc(first(institutional.explanation, '等待法人資料補齊。'))}</p></div></div>${industries.length ? `<div class="v20-daily-block"><h4>熱門產業</h4><div class="v20-chip-row">${industries.map(item => `<span>${esc(item.industry || item.name || item)}${num(item.averageChangePct) == null ? '' : ` ${displayPercent(item.averageChangePct)}`}</span>`).join('')}</div></div>` : ''}${focus.length ? `<div class="v20-daily-block"><h4>值得關注</h4><div class="v20-report-stocks">${focus.map(item => `<button type="button" data-v20-detail="${esc(item.symbol)}"><b>${esc(item.name || item.symbol)}</b><small>${esc(item.symbol)} · ${esc(first(item.whyNotice, item.advantage, '查看量化分析'))}</small></button>`).join('')}</div></div>` : ''}${risks.length ? `<div class="v20-daily-block"><h4>主要風險</h4><ul>${risks.map(item => `<li><b>${esc(item.title || '風險提醒')}</b> ${esc(item.explanation || item.risk || item)}</li>`).join('')}</ul></div>` : ''}<div class="v20-daily-block"><h4>自選股變化</h4>${changes.length ? `<ul>${changes.map(item => `<li>${esc(typeof item === 'string' ? item : first(item.explanation, item.message, item.title, item.symbol))}</li>`).join('')}</ul>` : '<p class="muted">目前沒有已驗證的重要變化。</p>'}</div></article></section>`;
  }

  function homePageV20() {
    const home = v20.home || {};
    const market = home.market || {};
    const news = safeArray(home.importantNews);
    const newsReason = first(home.importantNewsState?.reason, '此推薦批次尚未保存可驗證的新聞與公告快照。');
    const visibleDegraded = visibleDegradedSources(home.degradedSources, market);
    const state = statusBanner({
      ...home,
      dataState: visibleDegraded.length ? home.dataState : 'complete',
      degradedSources: visibleDegraded,
    }, v20.homePhase, v20.homeError);
    return `<div class="v20-dashboard">
      ${pageHero('MARKET INTELLIGENCE · v20', '今日重點', '先看結論，再展開需要的細節。', state)}
      <section class="v20-section"><div class="v20-section-title"><div><span>MARKET REGIME</span><h3>今日市場環境</h3></div><strong>${esc(market.regime || '資料不足')}</strong></div>
        <div class="card v20-market-panel"><div class="v20-market-grid">${marketCard('加權指數', market.taiex)}${marketCard('櫃買指數', market.tpex)}${marketCard('台指期', market.txFutures)}</div><div class="v20-regime-line"><span>市場強弱</span><b>${displayNumber(market.regimeScore, 0)} / 100</b><span>信心 ${probability(market.confidence)}</span></div>${globalStrip(market)}</div>
      </section>
      ${dailyReportSection()}
      <div class="v20-home-columns"><section class="v20-section"><div class="v20-section-title"><div><span>SHORT-TERM</span><h3>短期 Top 5</h3></div><small>2／3／5／10 日</small></div>${compactList(safeArray(home.shortTop), 'short')}</section>
      <section class="v20-section"><div class="v20-section-title"><div><span>MID-TERM</span><h3>中期 Top 5</h3></div><small>2／4／8 週</small></div>${compactList(safeArray(home.mediumTop), 'medium')}</section></div>
      <section class="v20-section"><div class="v20-section-title"><div><span>DISCLOSURES</span><h3>重要新聞與公告</h3></div><small>${news.length ? `顯示 ${Math.min(v20.newsVisible, news.length)}／${news.length} 則` : '此批次未收錄'}</small></div>${news.length ? `<div class="card v20-news-list">${news.slice(0, v20.newsVisible).map(item => `<article><div><b>${esc(item.title || '未命名公告')}</b><small>${esc(first(item.companyName, item.source, '公開來源'))} · ${esc(first(item.eventDate, item.publishedAt?.slice?.(0, 10), '日期待補'))}</small></div><span class="tag ${item.sentimentLabel === 'harm' ? 'bad' : item.sentimentLabel === 'benefit' ? '' : 'info'}">${item.sentimentLabel === 'harm' ? '風險' : item.sentimentLabel === 'benefit' ? '正向' : '中性'}</span></article>`).join('')}</div>${v20.newsVisible < news.length ? '<button id="v20NewsMore" class="v20-more-link" type="button">載入更多新聞與公告</button>' : ''}` : `<div class="card v20-empty"><b>不可驗證的內容不顯示</b><p>${esc(newsReason)}</p></div>`}</section>
      ${disclaimer()}
    </div>`;
  }

  function rankingFilters(model, page) {
    const label = model === 'short' ? '短期' : '中期';
    const horizonLabel = value => model === 'medium' ? `${value / 5} 週（${value} 個交易日）` : `${value} 個交易日`;
    return `<div class="card v20-filters"><div class="v20-filter-grid"><label>觀察期間<select id="v20Horizon">${HORIZONS[model].map(value => `<option value="${value}" ${page.horizon === value ? 'selected' : ''}>${horizonLabel(value)}</option>`).join('')}</select></label><label>市場<select id="v20Market"><option value="all">全部</option><option value="listed" ${page.market === 'listed' ? 'selected' : ''}>上市</option><option value="otc" ${page.market === 'otc' ? 'selected' : ''}>上櫃</option><option value="etf" ${page.market === 'etf' ? 'selected' : ''}>ETF</option></select></label><label>產業<input id="v20Industry" value="${esc(page.industry)}" placeholder="全部產業"></label><label>排序<select id="v20Sort"><option value="net_opportunity_desc" ${page.sort === 'net_opportunity_desc' ? 'selected' : ''}>成本後機會值</option><option value="score_desc" ${page.sort === 'score_desc' ? 'selected' : ''}>機會分數</option><option value="risk_asc" ${page.sort === 'risk_asc' ? 'selected' : ''}>風險較低</option><option value="change_desc" ${page.sort === 'change_desc' ? 'selected' : ''}>排名上升</option></select></label></div><div class="search-row"><input id="v20Search" value="${esc(page.search)}" inputmode="search" placeholder="搜尋股票代號或名稱" aria-label="搜尋${label}機會股"><button id="v20SearchBtn" class="btn" type="button">搜尋</button></div></div>`;
  }

  function rankingPageV20(model) {
    const page = v20.pages[model];
    const visibleItems = publicModelRows(page.items, model)
      .filter(row => publicHorizon(row) === page.horizon);
    const label = model === 'short' ? '短期機會股' : '中期機會股';
    const description = model === 'short' ? '尋找量價、突破、籌碼與事件形成的短波段。' : '尋找成長、產業趨勢、法人布局與中期趨勢。';
    const status = statusBanner({ dataState: page.phase, dataDate: page.dataDate, completeness: page.completeness, dataCompleteness: page.dataCompleteness, publicationPhase: page.publicationPhase, enrichmentPending: page.enrichmentPending, degradedSources: page.degradedSources }, page.phase, page.error);
    return `<div class="v20-ranking-page">${pageHero(model === 'short' ? 'SHORT-TERM MODEL' : 'MID-TERM MODEL', label, description, status)}${rankingFilters(model, page)}
      <div class="v20-results-head"><div><b>${visibleItems.length} 檔</b><small>資料日期 ${esc(page.dataDate || S.date || '待補')}</small></div><span>分數與風險分開呈現</span></div>
      <div class="v20-card-list">${visibleItems.map(row => modelCard(row)).join('') || `<div class="card v20-empty">${page.loading ? '<span class="spinner"></span> 正在局部更新排行，其他頁面仍可使用。' : '目前沒有通過硬性條件且資料完整的股票。'}</div>`}</div>
      ${page.nextCursor ? `<button id="v20LoadMore" class="btn secondary v20-load-more" type="button" ${page.loading ? 'disabled' : ''}>${page.loading ? '載入中…' : '載入更多 20 檔'}</button>` : ''}${disclaimer()}</div>`;
  }

  function watchlistRowsV20() {
    const watched = getWatchlist();
    return watched.map(item => {
      const symbol = String(item.symbol || '');
      const detail = v20.detailCache.get(symbol) || readCache(`stock:${symbol}`);
      const short = safeArray(detail?.short).find(signal => signal.horizon === DEFAULT_HORIZON.short) || safeArray(detail?.short)[0];
      const mediumRows = publicModelRows(detail?.medium, 'medium');
      const medium = mediumRows.find(signal => publicHorizon(signal) === DEFAULT_HORIZON.medium) || mediumRows[0];
      return { item, detail, short, medium, stock: detail?.stock || S.stocks.find(stock => String(stock.symbol) === symbol) };
    }).filter(({ item }) => item.symbol);
  }

  function watchlistSectionV20() {
    const rows = watchlistRowsV20();
    return rows.length ? `<div class="v20-card-list">${rows.map(({ item, detail, short, medium, stock }) => {
        const reminder = localizeStrategyText(first(v20.watchErrors.get(String(item.symbol)), safeArray(short?.risks)[0], safeArray(medium?.risks)[0], safeArray(short?.reasons)[0], safeArray(medium?.reasons)[0], detail ? '目前沒有已驗證的新提醒。' : '正在背景載入量化分析。'));
        return `<article class="card v20-watch-card" data-v20-detail="${esc(item.symbol)}"><div class="head"><div><b>${esc(stock?.name || item.symbol)}</b><small>${esc(item.symbol)} · ${esc(first(stock?.market, '市場待補'))}</small></div><button type="button" class="icon-btn" data-watch="${esc(item.symbol)}">移除</button></div><div class="v20-watch-metrics"><div><small>最新價格</small><b>${displayNumber(first(stock?.close, stock?.price), 2)}</b></div><div><small>短期機會／風險</small><b>${displayNumber(short?.opportunityScore, 0)}／${displayNumber(short?.riskScore, 0)}</b></div><div><small>中期機會／風險</small><b>${displayNumber(medium?.opportunityScore, 0)}／${displayNumber(medium?.riskScore, 0)}</b></div><div><small>資料日期</small><b>${esc(first(detail?.dataDate, stock?.priceDate, S.date, '待補'))}</b></div></div><div class="v20-inline-note"><b>重要提醒：</b>${esc(reminder)}</div><button type="button" class="btn v20-full" data-v20-detail="${esc(item.symbol)}">查看短中期分析</button></article>`;
      }).join('')}</div>` : '<div class="card v20-empty"><h3>尚未加入自選股票</h3><p>可在短期、中期排行榜或個股分析中加入。</p></div>';
  }

  function watchlistPageV20() {
    return `<div class="v20-watch-page">${pageHero('WATCHLIST', '我的自選', '只保存關注股票，追蹤短中期排名、風險與條件變化；不記錄持股成本、損益或交易。')}${watchlistSectionV20()}${disclaimer()}</div>`;
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
          v20.watchErrors.set(symbol, '量化分析更新失敗；保留既有資料，可稍後重試。');
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

  function validationRows(payload) {
    const snapshot = payload?.forwardSnapshot || payload?.snapshot || payload?.latestSnapshot || {};
    const rows = first(snapshot?.summary, snapshot?.outcomes, payload?.summary, payload?.outcomes, []);
    return safeArray(rows);
  }

  function validationField(row, ...keys) {
    return first(...keys.map(key => row?.[key]));
  }

  function validationMetric(label, value, options = {}) {
    const numeric = num(value);
    const display = numeric == null
      ? '尚未提供'
      : options.percent === false
        ? displayNumber(numeric, options.digits ?? 0)
        : options.lossMagnitude
          ? `${numeric > 0 ? '-' : ''}${Math.abs(numeric).toFixed(options.digits ?? 2)}%`
          : displayPercent(numeric, options.digits ?? 2);
    return `<div><small>${esc(label)}</small><b class="${numeric > 0 && options.directional ? 'up' : numeric < 0 && options.directional ? 'down' : ''}">${display}</b></div>`;
  }

  function validationSummaryCard(row, index) {
    const sampleCount = num(validationField(row, 'sampleCount', 'sample_count', 'count')) || 0;
    const enough = sampleCount >= MIN_VALIDATION_SAMPLES;
    const model = validationField(row, 'model', 'modelKey', 'model_key') || v20.validationModel;
    const horizon = num(validationField(row, 'horizon', 'horizonDays', 'horizon_days')) || v20.validationHorizon;
    const strategy = validationField(row, 'strategy', 'strategyKey', 'strategy_key') || '全部策略';
    const regime = validationField(row, 'regime', 'marketRegime', 'market_regime') || '全部市場環境';
    return `<article class="card v20-validation-card"><div class="head"><div><span class="tag info">${esc(model === 'medium' ? '中期' : '短期')} · ${displayNumber(horizon, 0)} 日</span><h3>${esc(strategy)}</h3><small>${esc(regime)}</small></div><span class="status-pill ${enough ? 'ok' : ''}">${enough ? '樣本可檢視' : '樣本累積中'}</span></div>
      <div class="v20-validation-metrics">${validationMetric('有效樣本', sampleCount, { percent: false })}${validationMetric('成本後平均報酬', validationField(row, 'averageNetReturn', 'average_net_return'), { directional: true })}${validationMetric('平均超額報酬', validationField(row, 'averageExcessReturnNet', 'average_excess_return_net', 'averageExcessReturn', 'average_excess_return', 'excessReturn', 'excess_return'), { directional: true })}${validationMetric('已實現批次回撤', validationField(row, 'maxRealizedCohortDrawdown', 'max_realized_cohort_drawdown'), { lossMagnitude: true })}${validationMetric('平均 MFE', validationField(row, 'averageMfe', 'average_mfe'))}${validationMetric('平均 MAE', validationField(row, 'averageMae', 'average_mae'))}</div>
      ${enough ? '<div class="v20-inline-note"><b>解讀：</b>結果已達最低展示樣本，但仍應同時查看月份、市場環境與結果分布。</div>' : `<div class="notice"><b>資料不足：</b>目前 ${displayNumber(sampleCount, 0)} 筆，未達 ${MIN_VALIDATION_SAMPLES} 筆；不產生成功率或上漲機率。</div>`}
      <small class="muted">Forward snapshot #${esc(first(validationField(row, 'snapshotId', 'snapshot_id', 'runId', 'run_id'), index + 1))}</small></article>`;
  }

  function validationPageV20() {
    const payload = v20.validation || {};
    const snapshot = payload.forwardSnapshot || payload.snapshot || payload.latestSnapshot || {};
    const rows = validationRows(payload);
    const status = statusBanner(payload, v20.validationLoading ? 'refreshing' : payload.dataState, v20.validationError);
    const horizons = HORIZONS[v20.validationModel];
    return `<div class="v20-validation-page">${pageHero('STRATEGY VALIDATION', '策略驗證中心', '檢視當時不可修改的推薦快照與後續實際結果，不把歷史統計包裝成未來保證。', status)}
      <section class="card v20-validation-controls"><div class="v20-filter-grid"><label>模型<select id="v20ValidationModel"><option value="short" ${v20.validationModel === 'short' ? 'selected' : ''}>短期 2～10 日</option><option value="medium" ${v20.validationModel === 'medium' ? 'selected' : ''}>中期 2～8 週</option></select></label><label>驗證期間<select id="v20ValidationHorizon">${horizons.map(value => `<option value="${value}" ${v20.validationHorizon === value ? 'selected' : ''}>${v20.validationModel === 'medium' ? `${value / 5} 週（${value} 日）` : `${value} 個交易日`}</option>`).join('')}</select></label></div></section>
      <section class="card v20-forward-snapshot"><div class="v20-section-title"><div><span>FORWARD SNAPSHOT</span><h3>當時推薦快照</h3></div><strong>${esc(first(snapshot.modelVersion, snapshot.model_version, payload.modelVersion, payload.model_version, '版本待補'))}</strong></div><div class="v20-factor-grid"><div><small>資料日期</small><b>${esc(first(snapshot.dataDate, snapshot.data_date, payload.dataDate, '待補'))}</b></div><div><small>快照編號</small><b>${esc(first(snapshot.id, snapshot.runId, snapshot.run_id, payload.runId, payload.run_id, '待補'))}</b></div><div><small>方法</small><b>${esc(first(payload.methodology, snapshot.methodology, 'Point-in-time'))}</b></div><div><small>前視偏誤</small><b>${payload.noLookAhead === true || snapshot.noLookAhead === true ? '已禁止' : '狀態待補'}</b></div></div></section>
      <section class="v20-section"><div class="v20-section-title"><div><span>REALIZED OUTCOMES</span><h3>成本後實際結果</h3></div><small>${rows.length ? `${rows.length} 組結果` : '尚無成熟樣本'}</small></div>${v20.validationLoading && !rows.length ? '<div class="card v20-empty"><span class="spinner"></span> 正在讀取最近快照與成熟結果…</div>' : rows.length ? `<div class="v20-card-list">${rows.map(validationSummaryCard).join('')}</div>` : `<div class="card v20-empty"><h3>Forward snapshot 尚在累積結果</h3><p>目前沒有達到持有期且完成成本計算的樣本，因此不顯示命中率或推測機率。</p></div>`}${v20.validationError ? `<div class="notice">驗證資料載入失敗：${esc(v20.validationError)} <button id="v20ValidationRetry" class="btn secondary small-btn" type="button">重新載入</button></div>` : ''}</section>
      <section class="card v20-analysis-search"><h3>搜尋個股詳細分析</h3><p>個股搜尋仍保留在股票詳細頁，顯示短中期條件、風險與失效原因。</p><div class="search-row"><input id="v20AnalysisSymbol" value="${esc(v20.analysisSymbol)}" inputmode="latin" maxlength="7" placeholder="例如 2330" aria-label="股票代號"><button id="v20Analyze" class="btn" type="button">查看股票</button></div>${v20.analysisMessage ? `<div class="notice">${esc(v20.analysisMessage)}</div>` : ''}</section>
      ${disclaimer()}</div>`;
  }

  async function loadValidation() {
    if (v20.validationLoading) return;
    v20.validationLoading = true;
    v20.validationError = '';
    if (S.tab === 'validation') render();
    try {
      const payload = await apiJson(`/backtest?model=${encodeURIComponent(v20.validationModel)}&horizon=${encodeURIComponent(v20.validationHorizon)}`);
      v20.validation = payload;
      v20.validationLoaded = true;
    } catch (error) {
      v20.validationError = error.name === 'AbortError' ? '驗證資料讀取逾時。' : error.message;
      v20.validationLoaded = true;
    } finally {
      v20.validationLoading = false;
      if (S.tab === 'validation') render();
    }
  }

  function ensureValidation() {
    if (!v20.validationLoaded && !v20.validationLoading) void loadValidation();
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
    const sourceDates = Object.entries(detail?.sourceDates || {}).filter(([, value]) => value);
    return sourceDates.length
      ? `<section><h3>資料來源日期</h3><div class="card v20-factor-grid">${sourceDates.map(([key, value]) => `<div><small>${esc(key)}</small><b>${esc(value)}</b></div>`).join('')}</div></section>`
      : '';
  }

  function signalSection(signals, model, modelState = null) {
    const label = model === 'short' ? '短期模型' : '中期模型';
    const visibleSignals = publicModelRows(signals, model);
    if (!visibleSignals.length) return `<section><h3>${label}</h3><div class="card v20-empty"><b>${modelState?.status === 'query_failed' ? '模型查詢失敗' : '模型訊號尚未產生'}</b><p>${esc(modelState?.reason || `${label}工作尚未完成；行情、基本面完整度與模型預測狀態是不同項目。`)}</p></div></section>`;
    return `<section><h3>${label}</h3>${modelStateNotice(modelState)}<div class="v20-signal-grid">${visibleSignals.map(signal => {
      const forecast = forecastFor(signal);
      const validation = validatedForecast(signal, forecast);
      const range = forecast.returnRange || {};
      const invalidations = safeArray(signal.invalidationConditions);
      const reasons = safeArray(signal.reasons);
      const risks = safeArray(signal.risks);
      const forecastBlock = validation.publishable
        ? `<div class="v20-forecast-row"><div><small>歷史正報酬比例</small><b>${probability(forecast.upProbability)}</b></div><div><small>歷史成本後平均</small><b>${displayPercent(forecast.expectedNetReturn)}</b></div><div><small>樣本／完整度</small><b>${displayNumber(validation.samples, 0)}／${probability(signal.completeness)}</b></div></div>`
        : `<div class="v20-inline-note"><b>機率尚未公開：</b>${esc(hiddenForecastReason(validation))}目前仍可參考機會分數、風險、因子與交易條件。</div><div class="v20-forecast-row"><div><small>校準狀態</small><b>${validation.samples == null ? '樣本數待補' : `累積 ${displayNumber(validation.samples, 0)} 筆`}</b></div><div><small>模型信心</small><b>${probability(signal.confidence)}</b></div><div><small>資料完整度</small><b>${probability(signal.completeness)}</b></div></div>`;
      const calibratedRanges = validation.publishable ? `<span>歷史 P10／P50／P90 <b>${displayPercent(range.p10)}／${displayPercent(range.p50)}／${displayPercent(range.p90)}</b></span><span>MFE／MAE <b>${displayPercent(forecast.averageMfe)}／${displayPercent(forecast.averageMae)}</b></span>` : '';
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
    const stock = detail?.stock || detail?.short?.[0] || detail?.medium?.[0] || { symbol };
    const name = first(stock?.name, detail?.short?.[0]?.name, detail?.medium?.[0]?.name, symbol);
    return `<div class="modal"><div class="sheet v20-detail-sheet"><button class="sheet-close" type="button" aria-label="關閉">×</button><div class="v20-detail-head"><div><span class="v20-eyebrow">V20 QUANT ANALYSIS</span><h2>${esc(name)} <small>${esc(symbol)}</small></h2><p>${esc(first(stock?.market, stock?.industry, '市場資料待補'))} · 資料日期 ${esc(first(detail?.dataDate, stock?.priceDate, S.date, '待補'))}</p></div><button class="btn secondary" type="button" data-watch="${esc(symbol)}">${isWatched(symbol) ? '✓ 已自選' : '＋ 自選'}</button></div>
      ${statusBanner(detail || {}, loading ? 'refreshing' : detail?.dataState, error)}
      <div class="v20-quote"><div><small>最新盤後價格 · ${esc(first(detail?.tradeDate, stock?.priceDate, '日期待補'))}</small><strong>${displayNumber(first(stock?.close, stock?.price), 2)}</strong></div><div><small>當日漲跌</small><b class="${num(stock?.change) > 0 ? 'up' : num(stock?.change) < 0 ? 'down' : 'muted'}">${displayPercent(stock?.change, 2)}</b></div><div><small>資料完整度</small><b>${probability(detail?.completeness)}</b></div></div>
      <div class="card v20-factor-grid"><div><small>交易日期</small><b>${esc(first(detail?.tradeDate, '此批次未保存價格快照'))}</b></div><div><small>分析資料日期</small><b>${esc(first(detail?.analysisDataDate, '待補'))}</b></div><div><small>新聞與公告</small><b>${esc(first(detail?.newsPublishedAt?.slice?.(0, 16), detail?.newsState?.reason, '此批次未收錄'))}</b></div><div><small>分析產生時間</small><b>${esc(first(detail?.analysisGeneratedAt?.slice?.(0, 16), '待補'))}</b></div></div>
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
    qa('[data-v20-detail]', modalRoot).forEach(button => button.onclick = event => {
      event.preventDefault();
      event.stopPropagation();
      const relatedSymbol = button.dataset.v20Detail;
      if (relatedSymbol && relatedSymbol !== symbol) void openV20Detail(relatedSymbol);
    });
    const sheet = q('.sheet', modalRoot); if (sheet) sheet.scrollTop = scroll;
  }

  async function openV20Detail(symbol) {
    symbol = String(symbol || '').trim().toUpperCase();
    if (!/^[0-9]{4,6}[A-Z]?$/.test(symbol)) return;
    S.detailSymbol = symbol;
    const cachedCandidate = v20.detailCache.get(symbol) || readCache(`stock:${symbol}`);
    const cached = samePublication(cachedCandidate, v20.home) ? cachedCandidate : null;
    paintDetail(symbol, cached, true);
    try {
      const detail = await apiJson(`/stocks?symbol=${encodeURIComponent(symbol)}`);
      if (v20.home && !samePublication(detail, v20.home)) {
        void loadHome();
        throw new Error('推薦批次已更新，正在重新同步畫面。');
      }
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
      if (v20.home && !samePublication(payload, v20.home)) {
        void loadHome();
        throw new Error('推薦批次已更新，正在重新同步排行。');
      }
      const existing = append ? page.items : [];
      const bySymbol = new Map(existing.map(item => [item.symbol, item]));
      publicModelRows(payload.items, model)
        .filter(item => publicHorizon(item) === page.horizon)
        .forEach(item => bySymbol.set(item.symbol, item));
      page.items = [...bySymbol.values()];
      page.nextCursor = payload.nextCursor || null;
      page.totalEstimate = payload.totalEstimate || page.items.length;
      page.dataDate = payload.dataDate || page.dataDate;
      page.runId = payload.runId || null;
      page.publicationKey = payload.publicationKey || null;
      page.contentHash = payload.contentHash || null;
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
      const previousHome = v20.home;
      v20.home = payload;
      v20.homePhase = payload.dataState || 'partial';
      v20.homeError = '';
      S.loading = false;
      S.date = payload.dataDate || S.date;
      S.mode = payload.dataState === 'complete' ? 'live' : 'partial';
      updateMarketHeader();
      const atomicReport = unwrapDailyReport(payload.dailyReport);
      if (atomicReport && samePublication(atomicReport.meta, payload)) {
        v20.dailyReport = atomicReport;
        v20.dailyPhase = atomicReport.meta.publicationPhase || 'base_ready';
        v20.dailyError = '';
      } else {
        v20.dailyReport = null;
        v20.dailyPhase = 'error';
        v20.dailyError = '每日報告未綁定目前推薦批次，已停止顯示。';
      }
      if (previousHome && !samePublication(previousHome, payload)) {
        v20.detailCache.clear();
        Object.values(v20.pages).forEach(page => {
          if (page.runId && !samePublication(page, payload)) {
            page.items = [];
            page.nextCursor = null;
            page.totalEstimate = 0;
            page.loaded = false;
            page.phase = 'refreshing';
          }
        });
      }
      writeCache('home', payload);
    } catch (error) {
      v20.homePhase = v20.home ? 'cache' : 'error';
      v20.homeError = error.name === 'AbortError' ? '背景更新逾時，保留快取資料。' : error.message;
      S.loading = false;
      S.date = v20.home?.dataDate || S.date;
      S.mode = v20.home ? 'partial' : 'error';
      updateMarketHeader();
    }
    if (S.tab === 'home') render();
  }

  const legacyBind = bind;
  bind = function bindV20() {
    legacyBind();
    enforceDarkOnly();
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
    }
    if (S.tab === 'validation') {
      ensureValidation();
      q('#v20ValidationModel')?.addEventListener('change', event => {
        v20.validationModel = event.target.value === 'medium' ? 'medium' : 'short';
        v20.validationHorizon = DEFAULT_HORIZON[v20.validationModel];
        v20.validationLoaded = false;
        void loadValidation();
      });
      q('#v20ValidationHorizon')?.addEventListener('change', event => {
        const value = Number(event.target.value);
        if (!HORIZONS[v20.validationModel].includes(value)) return;
        v20.validationHorizon = value;
        v20.validationLoaded = false;
        void loadValidation();
      });
      q('#v20ValidationRetry')?.addEventListener('click', () => {
        v20.validationLoaded = false;
        void loadValidation();
      });
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
    const aliases = { opportunities: 'short', mine: 'watchlist', watch: 'watchlist', analysis: 'validation' };
    const next = aliases[tab] || tab;
    if (!VALID_TABS.has(next)) return;
    S.tab = next;
    render();
    resetPageScroll();
    if (next === 'short' || next === 'medium') ensureRankings(next);
    if (next === 'watchlist') void ensureWatchDetails();
    if (next === 'validation') ensureValidation();
  };

  render = function renderV20() {
    const aliases = { opportunities: 'short', mine: 'watchlist', watch: 'watchlist', analysis: 'validation' };
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
            : validationPageV20();
    bind();
  };

  openDetail = openV20Detail;
  enforceDarkOnly();
  render();
  void loadHome();
})();
