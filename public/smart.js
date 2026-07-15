(() => {
  'use strict';

  const groupLabels = { listed: '上市股票', otc: '上櫃股票', etf: 'ETF' };
  const groupNotes = {
    listed: '上市股提高外資、成交金額與大盤連動的判斷比重。',
    otc: '上櫃股提高營收加速度、投信、大戶集中與流動性風險比重。',
    etf: 'ETF 不使用月營收、EPS、ROE或個股本益比，改看趨勢、流動性、規模與基金結構。'
  };
  let selectedGroup = 'listed';
  let officialOnly = true;
  let minimumScore = 60;
  let selectedIndustry = '全部產業';
  let snapshot = null;
  let backtest = null;
  let snapshotState = 'loading';
  const visibleCount = { listed: 20, otc: 20, etf: 20 };
  const EXPECTED_ANALYSIS_VERSION = '16.3-ultimate-data-audit';

  const finite = value => value != null && Number.isFinite(Number(value));
  const snapshotRows = group => Array.isArray(snapshot?.groups?.[group]) ? snapshot.groups[group] : [];
  const stockGroup = stock => stock.instrumentType === 'ETF' || /^00\d{2,4}[A-Z]?$/i.test(stock.symbol) ? 'etf' : stock.market === '上櫃' ? 'otc' : 'listed';
  const liveGroupRows = group => S.stocks.filter(stock => stockGroup(stock) === group);

  function compatibleSnapshot(payload) {
    if (String(payload?.version) !== '16.3' || !payload?.groups) return false;
    return Object.values(payload.groups).flat().every(row =>
      row?.analysis?.analysisVersion === EXPECTED_ANALYSIS_VERSION);
  }

  function ageLabel() {
    if (!snapshot?.generatedAt) return '尚未建立每日深度快照';
    const hours = (Date.now() - new Date(snapshot.generatedAt).getTime()) / 3600000;
    if (hours < 1) return '剛完成深度驗證';
    if (hours < 36) return `${Math.floor(hours)} 小時前完成深度驗證`;
    return `快照已 ${Math.floor(hours / 24)} 天，等待後端自動更新`;
  }

  function mergeSnapshots(base, backend) {
    if (!base && !backend) return null;
    const output = { ...(base || backend), groups: {}, backend: backend?.backend || base?.backend || null };
    Object.keys(groupLabels).forEach(group => {
      const bySymbol = new Map();
      const backendRows = backend?.groups?.[group] || [];
      const rows = backendRows.length ? backendRows : (base?.groups?.[group] || []);
      rows.forEach(row => bySymbol.set(String(row.stock?.symbol || ''), row));
      output.groups[group] = [...bySymbol.values()]
        .filter(row => row.stock?.symbol)
        .sort((a, b) => (b.result?.score ?? -1) - (a.result?.score ?? -1));
    });
    output.version = backend?.version || base?.version;
    output.generatedAt = [base?.generatedAt, backend?.generatedAt].filter(Boolean).sort().at(-1) || null;
    output.dataDate = [base?.dataDate, backend?.dataDate].filter(Boolean).sort().at(-1) || null;
    output.groupDates = { ...(base?.groupDates || {}), ...(backend?.groupDates || {}) };
    output.universe = { ...(base?.universe || {}), backendVerified: backend?.universe?.verifiedCandidates || {} };
    return output;
  }

  function provisionalScore(stock) {
    const growth = finite(stock.rev) ? Math.max(0, Math.min(35, stock.rev * .65 + 12)) : 0;
    const quality = finite(stock.roe) ? Math.max(0, Math.min(18, stock.roe)) : stock.eps > 0 ? 7 : 0;
    const chip = finite(stock.inst) && stock.volume ? Math.max(0, Math.min(15, stock.inst / stock.volume * 30 + 6)) : 0;
    const liquidity = finite(stock.value) ? Math.max(0, Math.min(20, (Math.log10(Math.max(stock.value, 1)) - 6) * 7)) : 0;
    const valuation = stock.pe > 0 ? Math.max(0, Math.min(12, 15 - stock.pe * .3)) : 2;
    if (stockGroup(stock) === 'etf') return Math.round(liquidity * 2 + Math.max(0, Math.min(25, (stock.change || 0) * 4 + 10)) + Math.min(15, (stock.yield || 0) * 2));
    return Math.max(0, Math.min(100, Math.round(growth + quality + chip + liquidity + valuation)));
  }

  function provisionalRows(group) {
    const floor = group === 'otc' ? 100 : group === 'etf' ? 500 : 300;
    return liveGroupRows(group)
      .filter(stock => stock.close != null && (stock.volume || 0) >= floor && !stock.hardExcluded)
      .map(stock => ({
        stock,
        analysis: null,
        result: {
          score: provisionalScore(stock), confidence: 45, official: false,
          tier: '快照初篩，尚待歷史驗證', categories: [], reasons: [], archetypes: ['待深度驗證'],
          risk: { deduction: 0, flags: [], hardExcluded: false, hardReasons: [] },
          missing: ['250 日價量', group === 'etf' ? 'ETF 基金結構' : '36 月營收、12 季財報與 20 日籌碼']
        }
      }))
      .sort((a, b) => b.result.score - a.result.score)
      .slice(0, 12);
  }

  function currentRows() {
    const deep = snapshotRows(selectedGroup);
    const rows = deep.length ? deep : provisionalRows(selectedGroup);
    return rows.filter(row => {
      if (officialOnly && !row.result.official) return false;
      if (finite(row.result.score) && row.result.score < minimumScore) return false;
      if (selectedGroup !== 'etf' && selectedIndustry !== '全部產業' && row.stock.industry !== selectedIndustry) return false;
      return true;
    }).slice(0, visibleCount[selectedGroup]);
  }

  function categoryBars(result) {
    if (!result.categories?.length) return '<div class="muted small">歷史深度資料尚未完成，因此不顯示假精準的分項分數。</div>';
    return `<div class="ultimate-factors">${result.categories.map(category => `<div class="ultimate-factor"><span>${esc(category.label)}</span><div role="progressbar" aria-label="${esc(category.label)}分數" aria-valuemin="0" aria-valuemax="100"${category.score == null ? '' : ` aria-valuenow="${fmt(category.score, 0)}"`}><i style="width:${category.score ?? 0}%"></i></div><b>${category.score == null ? '—' : fmt(category.score, 0)}</b><small>${fmt(category.coverage, 0)}%</small></div>`).join('')}</div>`;
  }

  function companyMetrics(row) {
    const revenue = row.analysis?.revenue || {};
    const financial = row.analysis?.financial || {};
    const chip = row.analysis?.institutional || {};
    const price = row.analysis?.price || {};
    const diagnostics = row.analysis?.sourceDiagnostics || {};
    const sourceReason = (diagnostic, emptyLabel) => {
      if (diagnostic?.status === 'upstream-error') return `API 取得失敗${diagnostic.statusCode ? `（HTTP ${diagnostic.statusCode}）` : ''}`;
      if (diagnostic?.status === 'stale-source-period') return `來源僅到 ${diagnostic.actualPeriod || '未知期別'}`;
      if (diagnostic?.status === 'empty-no-history') return 'API 成功，但該檔無歷史資料';
      return emptyLabel;
    };
    const revenueAmount = finite(revenue.revenue) ? Number(revenue.revenue) : finite(row.stock?.revenue) ? Number(row.stock.revenue) : null;
    const revenueLabel = revenueAmount == null ? reasonDash(sourceReason(diagnostics.revenue, '等待後端重驗')) : revenueAmount >= 100000000 ? `${fmt(revenueAmount / 100000000)} 億` : `${fmt(revenueAmount / 10000)} 萬`;
    const legacySnapshot = !String(row.analysis?.analysisVersion || '').startsWith('16.3');
    const quarterRevenueAmount = finite(financial.revenue)
      ? Number(financial.revenue)
      : finite(row.stock?.quarterRevenue) ? Number(row.stock.quarterRevenue) : null;
    const quarterRevenueLabel = finite(quarterRevenueAmount)
      ? `${fmt(quarterRevenueAmount / 100000000)} 億`
      : reasonDash(legacySnapshot
        ? '舊備援快照未含此欄，等待後端重驗'
        : financial.revenueStatus === 'source-not-comparable'
          ? '該產業報表沒有可比的單一營業額'
          : sourceReason(diagnostics.income, '等待後端重驗'));
    const cashConversionLabel = finite(financial.cashConversion)
      ? `${fmt(financial.cashConversion)} 倍`
      : reasonDash(financial.cashConversionBasis === 'TTM-nonpositive-net-income'
        ? '近四季淨利非正，不適用'
        : '現金流或正盈餘不足');
    return `${metric('最新月營收', revenueLabel, revenue.period || row.stock?.revPeriod || '')}
      ${metric('最新季營業額', quarterRevenueLabel, financial.period || row.stock?.quarterRevenuePeriod || '')}
      ${metric('3 月平均營收年增', finite(revenue.avg3Yoy) ? pct(revenue.avg3Yoy) : reasonDash('歷史不足'), revenue.period || '')}
      ${metric('營收加速度', finite(revenue.acceleration3) ? pct(revenue.acceleration3) : reasonDash('歷史不足'), revenue.consecutiveAcceleration ? `連升 ${revenue.consecutiveAcceleration} 期` : '')}
      ${metric('20 日法人買賣超', finite(chip.inst20) ? `${fmt(chip.inst20, 0)} 張` : reasonDash('歷史不足'), finite(chip.intensity5) ? `近 5 日占量 ${fmt(chip.intensity5, 1)}%` : '')}
      ${metric('20 日相對大盤', finite(price.relative20) ? pct(price.relative20) : reasonDash('指數或價格不足'))}
      ${metric('營業利益率', finite(financial.operatingMargin) ? `${fmt(financial.operatingMargin)}%` : reasonDash('財報不足'), finite(financial.operatingMarginYoyChange) ? `年變化 ${pct(financial.operatingMarginYoyChange)}` : '')}
      ${metric('近四季現金轉換', cashConversionLabel, finite(financial.ttmOperatingCashFlow) ? `TTM 營業現金流 ${fmt(financial.ttmOperatingCashFlow / 100000000)} 億` : financial.cashConversionBasis === 'latest-quarter' ? '近四季不足，暫用最新季' : 'TTM 平滑單季營運資金波動')}`;
  }

  function companyKeyMetrics(row) {
    const revenue = row.analysis?.revenue || {};
    const chip = row.analysis?.institutional || {};
    const price = row.analysis?.price || {};
    return `${metric('3 月平均營收年增', finite(revenue.avg3Yoy) ? pct(revenue.avg3Yoy) : reasonDash('歷史不足'), revenue.period || '')}
      ${metric('營收加速度', finite(revenue.acceleration3) ? pct(revenue.acceleration3) : reasonDash('歷史不足'), revenue.consecutiveAcceleration ? `連升 ${revenue.consecutiveAcceleration} 期` : '')}
      ${metric('20 日法人買賣超', finite(chip.inst20) ? `${fmt(chip.inst20, 0)} 張` : reasonDash('歷史不足'), finite(chip.intensity5) ? `近 5 日占量 ${fmt(chip.intensity5, 1)}%` : '')}
      ${metric('20 日相對大盤', finite(price.relative20) ? pct(price.relative20) : reasonDash('指數或價格不足'))}`;
  }

  function dataNotes(row) {
    const margin = row.analysis?.margin || {};
    const revenue = row.analysis?.revenue || {};
    const financial = row.analysis?.financial || {};
    const observedTradingDays = finite(revenue.postReleaseObservedDays)
      ? Number(revenue.postReleaseObservedDays)
      : null;
    const marginNote = String(margin.note || margin.sourceNote || '').toUpperCase();
    const diagnostics = row.analysis?.sourceDiagnostics || {};
    const diagnosticFor = value => {
      if (/季度營收|季營業額|季營收/.test(value)) return diagnostics.income;
      if (/營收|近 3 月平均年增|年增率連續|歷年同期新高/.test(value)) return diagnostics.revenue;
      if (/EPS|毛利|營業利益|淨利|財報|應收|存貨/.test(value)) return diagnostics.income || diagnostics.balance;
      if (/現金/.test(value)) return diagnostics.cashflow;
      if (/法人|外資|投信/.test(value)) return diagnostics.institutional;
      if (/融資|融券/.test(value)) return diagnostics.margin;
      if (/借券/.test(value)) return diagnostics.lending;
      if (/日線|均線|RSI|MACD|價量|突破|量能/.test(value)) return diagnostics.price;
      if (/大盤|市場指數|相對市場/.test(value)) return diagnostics.benchmark;
      return null;
    };
    const diagnosticLabel = (value, diagnostic) => {
      if (!diagnostic) return null;
      if (diagnostic.status === 'upstream-error') return `${value}：API 取得失敗${diagnostic.statusCode ? `（HTTP ${diagnostic.statusCode}）` : ''}`;
      if (diagnostic.status === 'stale-source-period') return `${value}：來源僅到 ${diagnostic.actualPeriod || '未知期別'}，應為 ${diagnostic.expectedPeriod || '最新期'}`;
      if (diagnostic.status === 'empty-no-history') return `${value}：上游 API 成功，但沒有該檔歷史資料`;
      return null;
    };
    const marginNotApplicable = margin.applicable === false || margin.marginEligible === false || margin.financingEligible === false || marginNote.includes('OX') ||
      (row.stock?.symbol === '5475' && Number(margin.marginBalance) === 0 && !finite(margin.marginUsage));
    return (row.result?.missing || []).map(value => {
      if (value === '營收公布後 5 日反應' && !finite(revenue.postRelease5) &&
          revenue.postReleaseStatus === 'pending-five-trading-days') {
        return { type: 'pending', label: observedTradingDays == null
          ? '營收公布後反應：待滿 5 個交易日'
          : `營收公布後反應：待滿 5 個交易日（目前 ${observedTradingDays} 日）` };
      }
      if (value === '融資使用率' && marginNotApplicable) return { type: 'na', label: '融資：不適用（不可融資）' };
      if (value === '單月營收年增' && revenue.yoyStatus === 'prior-year-zero') {
        return { type: 'na', label: '月營收年增：去年同期為 0，數學上不適用' };
      }
      if (/現金轉換/.test(value) && financial.cashConversionBasis === 'TTM-nonpositive-net-income') {
        return { type: 'na', label: '近四季現金轉換：淨利非正，該比率不具判讀意義' };
      }
      if (/集保|400 張|10 張以下/.test(value)) return { type: 'na', label: `${value}：該週集保檔未列出，不是每日 API 錯誤` };
      const sourceLabel = diagnosticLabel(value, diagnosticFor(value));
      if (sourceLabel) return { type: 'api', label: sourceLabel };
      if (/歷史僅|未滿 120|24～36|8～12|20 日/.test(value)) return { type: 'history', label: `${value}：客觀歷史筆數不足，會自動續補` };
      return { type: 'missing', label: value };
    });
  }

  function etfMetrics(row) {
    const price = row.analysis?.price || {};
    const etf = row.analysis?.etf || {};
    return `${metric('20 日動能', finite(price.return20) ? pct(price.return20) : reasonDash('歷史不足'))}
      ${metric('相對市場', finite(price.relative20) ? pct(price.relative20) : reasonDash('指數不足'))}
      ${metric('5／20 日量能比', finite(price.volumeRatio) ? `${fmt(price.volumeRatio)} 倍` : reasonDash('歷史不足'))}
      ${metric('ATR 波動', finite(price.atrPct) ? `${fmt(price.atrPct)}%` : reasonDash('歷史不足'))}
      ${metric('追蹤指數', etf.benchmark ? esc(etf.benchmark) : reasonDash('基金資料不足'))}
      ${metric('即時折溢價', finite(etf.premiumDiscount) ? pct(etf.premiumDiscount) : reasonDash('TWSE MIS 未回傳'), etf.navUpdatedAt || '')}
      ${metric('基金結構', etf.leveraged ? '槓桿型' : etf.inverse ? '反向型' : etf.fundType ? '一般型' : reasonDash('未辨識'))}`;
  }

  function etfKeyMetrics(row) {
    const price = row.analysis?.price || {};
    return `${metric('20 日動能', finite(price.return20) ? pct(price.return20) : reasonDash('歷史不足'))}
      ${metric('相對市場', finite(price.relative20) ? pct(price.relative20) : reasonDash('指數不足'))}
      ${metric('5／20 日量能比', finite(price.volumeRatio) ? `${fmt(price.volumeRatio)} 倍` : reasonDash('歷史不足'))}
      ${metric('ATR 波動', finite(price.atrPct) ? `${fmt(price.atrPct)}%` : reasonDash('歷史不足'))}`;
  }

  function trendFor(row) {
    return row.result?.trend || row.trend || row.context?.trend || row.analysis?.context?.trend || row.analysis?.trend || null;
  }

  function trendBadges(row) {
    const trend = trendFor(row), status = String(trend?.status || '').toLowerCase();
    const rankDelta = finite(trend?.rankDelta) ? Number(trend.rankDelta) : null;
    const scoreDelta = finite(trend?.scoreDelta) ? Number(trend.scoreDelta) : null;
    const previousRank = finite(trend?.previousRank) ? Number(trend.previousRank) : null;
    const historyCount = Array.isArray(trend?.history) ? trend.history.length : Number(trend?.count || 0);
    if (['accumulating', 'insufficient', 'pending'].includes(status) || (rankDelta == null && scoreDelta == null && previousRank == null)) {
      return `<div class="smart-trend"><span class="tag warn">歷史分數累積中${historyCount ? ` · ${historyCount} 份` : ''}</span></div>`;
    }
    const values = [];
    if (rankDelta != null) values.push(`<span class="tag info">排名 ${rankDelta > 0 ? `↑${fmt(rankDelta, 0)}` : rankDelta < 0 ? `↓${fmt(Math.abs(rankDelta), 0)}` : '持平'}</span>`);
    if (scoreDelta != null) values.push(`<span class="tag ${scoreDelta < 0 ? 'warn' : ''}">分數 ${scoreDelta > 0 ? '+' : ''}${fmt(scoreDelta, 1)}</span>`);
    return `<div class="smart-trend">${values.join('')}</div>`;
  }

  function opportunityCard(row, rank) {
    const { stock, result } = row;
    const formal = result.official;
    const notes = dataNotes(row);
    const missingCount = notes.filter(note => !['na', 'pending'].includes(note.type)).length;
    const risks = [...(result.risk?.hardReasons || []), ...(result.risk?.flags || [])];
    const category = result.categories?.slice().sort((a, b) => (b.score ?? -1) - (a.score ?? -1))[0];
    const mainReasons = [...new Set([...(result.archetypes || []), ...(result.reasons || [])])].slice(0, 2);
    const confidence = finite(result.confidence) ? Math.max(0, Math.min(100, Number(result.confidence))) : 0;
    const keyMetrics = selectedGroup === 'etf' ? etfKeyMetrics(row) : companyKeyMetrics(row);
    const allMetrics = selectedGroup === 'etf' ? etfMetrics(row) : companyMetrics(row);
    return `<article class="card ultimate-card ${formal ? 'formal' : 'provisional'}">
      <div class="ultimate-rank">${rank}</div>
      <div class="head"><div><div class="row wrap"><b class="smart-name">${esc(stock.name)}</b><span class="tag ${formal ? '' : 'warn'}">${formal ? '正式候選' : '驗證／信心未達標'}</span>${row.isStale ? `<span class="tag warn">沿用 ${esc(row.dataDate || '前次')} 驗證</span>` : ''}</div><div class="muted">${stock.symbol} · ${esc(groupLabels[selectedGroup])}${stock.industry ? ` · ${esc(stock.industry)}` : ''}</div></div><div class="smart-score"><small>最終分數</small><strong>${finite(result.score) ? result.score : '—'}</strong></div></div>
      ${trendBadges(row)}
      <div class="smart-price"><span class="price">${fmt(stock.close)}</span><b class="${cls(stock.change)}">${pct(stock.change)}</b></div>
      <div class="rules smart-reasons">${mainReasons.length ? mainReasons.map(value => `<span>${esc(value)}</span>`).join('') : '<span>等待深度原因資料</span>'}</div>
      <div class="grid ultimate-key-metrics">${keyMetrics}</div>
      <div class="ultimate-confidence"><div><span>資料信心</span><b>${fmt(confidence, 0)}%</b></div><div class="progress" role="progressbar" aria-label="${esc(stock.name)}資料信心" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${fmt(confidence, 0)}"><span style="width:${confidence}%"></span></div><small>${esc(result.tier || '')}${category ? ` · 最強項 ${esc(category.label)}` : ''}</small></div>
      <details class="ultimate-research"><summary>展開完整研究資料</summary><div class="grid three ultimate-metrics">${allMetrics}</div>${categoryBars(result)}${risks.length ? `<div class="ultimate-risk"><b>風險扣分 ${result.risk?.deduction || 0}</b>：${risks.map(esc).join('、')}</div>` : ''}<div class="ultimate-missing embedded"><div>${notes.length ? notes.map(note => `<span data-state="${note.type}">${esc(note.label)}</span>`).join('') : '<span data-state="complete">核心欄位完整</span>'}</div></div><div class="muted small">${missingCount ? `資料缺漏 ${missingCount} 項` : '資料狀態正常'}${notes.length > missingCount ? ` · ${notes.length - missingCount} 項待確認／不適用` : ''}</div></details>
      <div class="row smart-actions"><button class="btn grow" data-forecast="${stock.symbol}">深度趨勢頁</button><button class="btn secondary" data-watch="${stock.symbol}">${isWatched(stock.symbol) ? '★ 已自選' : '＋自選'}</button></div>
    </article>`;
  }

  function backtestPanel() {
    const data = backtest || snapshot?.backtest;
    const groupHorizon = data?.byGroup?.[selectedGroup]?.['20'] || data?.byGroup?.[selectedGroup]?.[20] || null;
    const ready = groupHorizon ? groupHorizon.status !== 'insufficient_history' && finite(groupHorizon.count) : data?.status === 'ready';
    if (!data || !ready) {
      const count = groupHorizon?.maturedDateCount ?? data?.snapshotCount;
      const minimum = groupHorizon?.minimumSnapshots ?? data?.minimumSnapshots ?? 25;
      return `<section class="card"><div class="head"><div><h3>點時回測</h3><div class="muted">訊號後次一交易日開盤進場，不倒填未來資料。</div></div><span class="tag warn">累積中</span></div><p class="muted">${esc(data?.message || `至少 ${minimum} 個成熟訊號日才公布結果。`)} ${finite(count) ? `目前 ${count} / ${minimum} 份。` : ''}</p></section>`;
    }
    const horizon = groupHorizon || data.horizons?.['20'] || data.horizons?.[20] || {};
    return `<section class="card"><div class="head"><div><h3>點時回測</h3><div class="muted">${groupLabels[selectedGroup]}排名前 10 · 次日開盤進場 · 不偷看未來</div></div><span class="tag">可檢驗</span></div><div class="grid four">${metric('20 日平均報酬', pct(horizon.averageReturn))}${metric('20 日超額報酬', pct(horizon.averageExcessReturn))}${metric('20 日勝率', finite(horizon.winRate) ? `${fmt(horizon.winRate)}%` : '—')}${metric('平均最大回撤', pct(horizon.averageMae))}</div></section>`;
  }

  opportunitiesPage = function () {
    const deepRows = snapshotRows(selectedGroup);
    const all = deepRows.length ? deepRows : provisionalRows(selectedGroup);
    const industries = ['全部產業', ...new Set(all.map(row => row.stock.industry).filter(Boolean))];
    if (!industries.includes(selectedIndustry)) selectedIndustry = '全部產業';
    const rows = currentRows();
    const counts = Object.fromEntries(Object.keys(groupLabels).map(group => [group, S.stocks.filter(stock => stockGroup(stock) === group).length]));
    const formalCount = deepRows.filter(row => row.result?.official).length;
    const persistentCount = Number(snapshot?.backend?.counts?.[selectedGroup]) || 0;
    const verifiedCount = Math.max(deepRows.length, persistentCount);
    const stateClass = snapshotState === 'ready' ? 'ok' : snapshotState === 'error' ? 'bad' : 'warn';
    return `<div class="smart-hero compact"><div><h2>機會股排行</h2><p>上市、上櫃與 ETF 分組評分；資料不足、待觀察與不適用會分開標示。</p></div><span class="status-pill ${stateClass}">${snapshotState === 'ready' ? (persistentCount ? `後端已累積 ${persistentCount} 檔` : '深度快照已載入') : snapshotState === 'error' ? '目前使用快照初篩' : '正在讀取深度快照'}</span></div>
      <details class="card ultimate-policy method-summary"><summary><b>評分方法</b><span class="tag info">${esc(ageLabel())}</span></summary><div class="muted">風險排除 → 成長確認 → 籌碼確認 → 價量進場判斷</div><div class="ultimate-pipeline"><span>硬性排除</span><i>→</i><span>成長 30</span><i>→</i><span>籌碼 25</span><i>→</i><span>價量 25</span><i>→</i><span>估值 10</span><i>→</i><span>環境 10</span></div><p class="muted">缺漏項目會移除權重並重正規化；資料信心低於 70% 不進正式榜。風險最高扣 30 分，交易限制與價格未還原直接排除。</p></details>
      <section class="card smart-filter-card"><div class="head"><div><h3>獨立排行榜</h3><div class="muted">${groupNotes[selectedGroup]}</div></div><button id="ultimateRefresh" class="btn secondary">重新讀取</button></div><div class="smart-groups" role="group" aria-label="市場分組">${Object.entries(groupLabels).map(([group, label]) => `<button data-ultimate-group="${group}" class="${selectedGroup === group ? 'active' : ''}" aria-pressed="${selectedGroup === group}">${label}<small>${counts[group] || 0}</small></button>`).join('')}</div><div class="ultimate-controls"><label>榜單<select id="ultimateOfficial"><option value="official" ${officialOnly ? 'selected' : ''}>只看正式候選</option><option value="all" ${!officialOnly ? 'selected' : ''}>含驗證中候選</option></select></label><label>最低分數<input id="ultimateMinScore" type="number" min="0" max="100" value="${minimumScore}"></label>${selectedGroup === 'etf' ? '' : `<label>產業<select id="ultimateIndustry">${industries.map(value => `<option ${value === selectedIndustry ? 'selected' : ''}>${esc(value)}</option>`).join('')}</select></label>`}</div></section>
      <div class="smart-results-head"><div><h3>${groupLabels[selectedGroup]}正式排序</h3><div class="muted">深度驗證 ${verifiedCount} 檔 · 信心達標 ${formalCount} 檔 · 顯示 ${rows.length} 檔${snapshot?.backend?.persistent ? ' · 後端持續累積' : ''}</div></div><b>${snapshot?.groupDates?.[selectedGroup] || snapshot?.dataDate || S.date || '日期核對中'}</b></div>
      ${rows.length ? `<div class="list ultimate-results">${rows.map((row, index) => opportunityCard(row, index + 1)).join('')}</div>${rows.length >= visibleCount[selectedGroup] ? '<button id="ultimateMore" class="btn secondary load-more">再顯示 20 檔</button>' : ''}` : `<div class="card empty"><h3>目前沒有符合正式門檻的標的</h3><p class="muted">這不是錯誤：可能是資料信心未滿 70%、分數低於 ${minimumScore}，或所有候選被風險規則排除。可切換「含驗證中候選」查看原因。</p></div>`}
      ${backtestPanel()}
      <details class="data-limit"><summary>資料限制</summary><p>ETF 的即時淨值折溢價、追蹤誤差、內扣費用與成分集中度若無穩定公開介面，系統會明列缺漏並降低信心，不會拿公司月營收或 ROE 代替。集保資料為每週資料，不當成每日訊號。</p></details>
      ${disclaimer()}`;
  };

  function bindUltimate() {
    qa('[data-ultimate-group]').forEach(button => button.onclick = () => {
      selectedGroup = button.dataset.ultimateGroup;
      selectedIndustry = '全部產業';
      render();
    });
    q('#ultimateOfficial')?.addEventListener('change', event => { officialOnly = event.target.value === 'official'; render(); });
    q('#ultimateMinScore')?.addEventListener('change', event => { minimumScore = Math.max(0, Math.min(100, Number(event.target.value) || 0)); render(); });
    q('#ultimateIndustry')?.addEventListener('change', event => { selectedIndustry = event.target.value; render(); });
    q('#ultimateRefresh')?.addEventListener('click', () => loadSnapshot(true));
    q('#ultimateMore')?.addEventListener('click', () => { visibleCount[selectedGroup] += 20; render(); });
  }

  async function loadSnapshot(force = false) {
    snapshotState = 'loading';
    if (S.tab === 'opportunities') render();
    let staticSnapshot = null;
    let backendSnapshot = null;
    const backtestPromise = fetch(`/api/market-data?type=ranking-backtest${force ? '&refresh=1' : ''}`, { cache: 'no-store' })
      .then(response => response.ok ? response.json() : null)
      .then(async payload => payload?.byGroup ? payload : fetch('/data/backtest.json?v=17.3.3', { cache: 'no-store' })
        .then(response => response.ok ? response.json() : null).catch(() => null))
      .catch(() => fetch('/data/backtest.json?v=17.3.3', { cache: 'no-store' })
        .then(response => response.ok ? response.json() : null).catch(() => null));
    try {
      const response = await fetch(`/api/market-data?type=backend-rankings&limit=40${force ? '&refresh=1' : ''}`, { cache: 'no-store' });
      if (response.ok) {
        const payload = await response.json();
        if (payload?.groups) backendSnapshot = payload;
      }
    } catch {}
    if (!backendSnapshot) {
      try {
        const response = await fetch('/data/latest.json?v=17.3.3', { cache: 'no-store' });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = await response.json();
        if (!payload.generatedAt || !payload.groups) throw new Error(payload.message || '每日快照尚未建立');
        if (!compatibleSnapshot(payload)) throw new Error('舊模型快照不作為 v16.3 正式候選');
        staticSnapshot = payload;
      } catch {}
    }
    snapshot = mergeSnapshots(staticSnapshot, backendSnapshot);
    snapshotState = snapshot ? 'ready' : 'error';
    // Backtest is rebuilt after the daily snapshot, so it must be read from its
    // own file instead of trusting the older copy embedded in latest.json.
    const updatedBacktest = await backtestPromise;
    if (updatedBacktest) backtest = updatedBacktest;
    if (S.tab === 'opportunities') render();
  }

  globalThis.twssUltimateSnapshot = () => snapshot;
  globalThis.twssUltimateBacktest = () => backtest || snapshot?.backtest || null;
  const oldBind = bind;
  bind = function () { oldBind(); bindUltimate(); };
  const button = q('.bottom-nav [data-tab="opportunities"]');
  if (button) button.innerHTML = '<span>◆</span>機會選股';
  loadSnapshot();
})();
