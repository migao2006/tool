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
      <div class="row smart-actions"><button class="btn grow" data-analysis="${stock.symbol}">查看分析</button><button class="btn secondary" data-watch="${stock.symbol}">${isWatched(stock.symbol) ? '★ 已自選' : '＋自選'}</button></div>
    </article>`;
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
    q('#ultimateRefresh')?.addEventListener('click', () => loadSnapshot());
    q('#ultimateMore')?.addEventListener('click', () => { visibleCount[selectedGroup] += 20; render(); });
  }

  async function loadSnapshot() {
    snapshotState = 'loading';
    if (S.tab === 'opportunities') render();
    let staticSnapshot = null;
    let backendSnapshot = null;
    const staticPromise=(globalThis.twssLatestSnapshotPromise||fetch('/data/latest.json?v=19.2.0',{cache:'force-cache'}).then(response=>response.ok?response.json():null).catch(()=>null));
    try {const payload=await staticPromise;if(payload?.generatedAt&&payload?.groups&&compatibleSnapshot(payload))staticSnapshot=payload}catch{}
    snapshot = mergeSnapshots(staticSnapshot, null);
    snapshotState = snapshot ? 'ready' : 'loading';
    if (!S.loading) render();
    try {const response=await fetch('/api/market-data?type=backend-rankings&limit=40',{cache:'no-store'});if(response.ok){const payload=await response.json();if(payload?.groups)backendSnapshot=payload}}catch{}
    snapshot = mergeSnapshots(staticSnapshot, backendSnapshot);
    snapshotState = snapshot ? 'ready' : 'error';
    if (S.tab === 'opportunities') render();
  }

  globalThis.twssUltimateSnapshot = () => snapshot;
  globalThis.twssLoadUltimateSnapshot = loadSnapshot;
  const oldBind = bind;
  bind = function () { oldBind(); bindUltimate(); };
  const button = q('.bottom-nav [data-tab="opportunities"]');
  if (button) button.innerHTML = '<span>◆</span>排行';
  if (!document.querySelector('script[src^="/v20.js"]')) loadSnapshot();
})();

/* v19 progressive UI. The v19 API enriches the existing verified snapshot;
   every panel keeps a labelled local fallback when an endpoint is unavailable. */
(() => {
  const api = '/api/v19';
  const v19 = {
    home: null,
    rankings: null,
    benchmarks: null,
    rankingNextCursor: null,
    rankingLoading: false,
    rankingGeneration: 0,
    rankingIndustries: [],
    watchRows: [],
    watchFingerprint: null,
    watchGeneration: 0,
    detail: new Map(),
    dailyReport: readDailyReportCache(),
    dailyReportState: 'loading',
    newsVisible: 3,
    state: 'loading',
    query: '',
    market: 'all',
    industry: 'all',
    sort: 'score_desc',
    visible: 10
  };

  const number = value => value == null || value === '' || !Number.isFinite(Number(value)) ? null : Number(value);
  const array = value => Array.isArray(value) ? value : [];
  const first = (...values) => values.find(value => value != null && value !== '');
  const cleanArray = (...values) => values.flatMap(array).filter(value => value != null && value !== '');
  const hasDegradation = value => Array.isArray(value) ? value.length > 0 : Boolean(value);
  const groupLabel = value => ({ listed: '上市', otc: '上櫃', etf: 'ETF', 上市: '上市', 上櫃: '上櫃', ETF: 'ETF' })[value] || value || '未分類';
  const groupKey = stock => stock?.instrumentType === 'ETF' || /^00\d{2,4}[A-Z]?$/i.test(stock?.symbol || '') ? 'etf' : stock?.market === '上櫃' ? 'otc' : 'listed';
  const dateOnly = value => String(value || '').match(/^\d{4}-\d{2}-\d{2}/)?.[0] || '';
  const safeUrl = value => { try { const url = new URL(value, location.origin); return /^https?:$/.test(url.protocol) ? url.href : ''; } catch { return ''; } };
  const unwrap = payload => payload?.data && typeof payload.data === 'object' ? payload.data : payload;
  const DAILY_REPORT_CACHE='twss-v19-daily-report-cache';

  function readDailyReportCache(){try{const value=JSON.parse(localStorage.getItem('twss-v19-daily-report-cache')||'null');return value?.data&&typeof value.data==='object'?value.data:value}catch{return null}}
  function writeDailyReportCache(value){try{if(value)localStorage.setItem(DAILY_REPORT_CACHE,JSON.stringify(value))}catch{}}
  function enforceDarkMode() {
    document.documentElement.dataset.theme = 'dark';
    document.documentElement.style.colorScheme = 'dark';
    localStorage.removeItem('twss-theme-v19');
    q('meta[name="theme-color"]')?.setAttribute('content','#060d14');
  }

  async function optionalJson(path) {
    try {
      const response = await fetch(`${api}${path}`, { cache: 'no-store', headers: { accept: 'application/json' } });
      if (!response.ok) return null;
      return unwrap(await response.json());
    } catch { return null; }
  }

  async function optionalMarketJson() {
    try {
      const response = await fetch('/api/market-data?type=benchmarks', {
        cache: 'no-store', headers: { accept: 'application/json' }
      });
      return response.ok ? await response.json() : null;
    } catch { return null; }
  }

  function rankingQuery(limit, cursor = '') {
    const params = new URLSearchParams({ limit: String(limit), sort: v19.sort });
    if (cursor) params.set('cursor', cursor);
    if (v19.market !== 'all') params.set('market', v19.market);
    if (v19.industry !== 'all') params.set('industry', v19.industry);
    if (v19.query.trim()) params.set('search', v19.query.trim());
    return `/rankings?${params}`;
  }

  function applyRankingPage(payload, append = false) {
    if (!payload) return false;
    const incoming = Array.isArray(payload) ? payload : array(first(payload.items, payload.rows, payload.rankings));
    const previous = append ? apiRankingRows() : [];
    const merged = new Map(previous.map(item => [String(item.stock?.symbol || item.ranking?.symbol || item.symbol || ''), item]));
    incoming.forEach(item => merged.set(String(item.stock?.symbol || item.ranking?.symbol || item.symbol || ''), item));
    v19.rankings = Array.isArray(payload) ? { items: [...merged.values()] } : { ...payload, items: [...merged.values()] };
    v19.rankingNextCursor = first(payload.nextCursor, payload.next_cursor, null);
    const metaIndustries = cleanArray(payload.filters?.industries, payload.industries);
    const pageIndustries = incoming.map(item => first(item.stock?.industry, item.ranking?.industry, item.industry)).filter(Boolean);
    v19.rankingIndustries = [...new Set([...v19.rankingIndustries, ...metaIndustries, ...pageIndustries])].sort((a, b) => String(a).localeCompare(String(b), 'zh-Hant-TW'));
    return true;
  }

  async function reloadRankings() {
    const generation = ++v19.rankingGeneration;
    v19.rankingLoading = true;
    v19.rankings = { items: [], filters: { market: v19.market, industry: v19.industry, search: v19.query, sort: v19.sort } };
    v19.rankingNextCursor = null;
    v19.visible = 10;
    render();
    const page = await optionalJson(rankingQuery(10));
    if (generation !== v19.rankingGeneration) return;
    if (!applyRankingPage(page, false)) v19.rankings = null;
    v19.rankingLoading = false;
    render();
  }

  async function showMoreRankings() {
    if (v19.rankingLoading) return;
    const generation = v19.rankingGeneration;
    v19.rankingLoading = true;
    const button = q('#v19RankMore');
    if (button) { button.disabled = true; button.textContent = '載入中…'; }
    if (v19.rankingNextCursor) {
      const page = await optionalJson(rankingQuery(20, v19.rankingNextCursor));
      if (generation !== v19.rankingGeneration) return;
      applyRankingPage(page, true);
    }
    v19.visible += 20;
    v19.rankingLoading = false;
    render();
  }

  function snapshotRows() {
    const value = globalThis.twssUltimateSnapshot?.();
    if (!value?.groups) return [];
    return Object.entries(value.groups).flatMap(([group, rows]) => array(rows).map(row => ({
      ...row,
      _v19Group: group,
      _v19Source: '深度分析快照',
      dataDate: first(row.dataDate, value.groupDates?.[group], value.dataDate)
    })));
  }

  function apiRankingRows() {
    const data = v19.rankings;
    if (!data) return [];
    if (Array.isArray(data)) return data;
    if (Array.isArray(data.items)) return data.items;
    if (Array.isArray(data.rows)) return data.rows;
    if (Array.isArray(data.rankings)) return data.rankings;
    if (data.groups) return Object.entries(data.groups).flatMap(([group, rows]) => array(rows).map(row => ({ ...row, _v19Group: group })));
    return [];
  }

  function componentScores(raw, result, analysis) {
    const direct = first(raw.componentScores, raw.scores, analysis.componentScores, analysis.scores, result.categories);
    if (Array.isArray(direct)) return direct.map(item => ({
      label: first(item.label, item.name, item.key, item.category, '分項'),
      score: number(first(item.score, item.value, item.points)),
      max: number(first(item.max, item.maximum, 100))
    })).filter(item => item.score != null);
    if (direct && typeof direct === 'object') {
      const labels = { fundamental: '基本面', technical: '技術面', institutional: '法人籌碼', volumeMomentum: '量價動能', news: '新聞', risk: '風險' };
      return Object.entries(direct)
        .filter(([key]) => !['overall', 'confidence', 'completeness'].includes(key))
        .map(([key, value]) => ({
          label: labels[key] || value?.label || key,
          score: number(value?.score ?? value?.value ?? value),
          max: number(value?.max ?? 100)
        }))
        .filter(item => item.score != null);
    }
    return [];
  }

  function riskInfo(raw, result, analysis) {
    const risk = first(raw.risk, analysis.risk, result.risk, {});
    const explicit = String(first(raw.riskLevel, analysis.riskLevel, risk.level, '')).toLowerCase();
    const flags = cleanArray(raw.risks, raw.riskWarnings, analysis.risks, analysis.riskWarnings, risk.flags, risk.reasons).map(String);
    const deduction = number(first(risk.deduction, raw.riskDeduction, analysis.riskDeduction));
    const hard = Boolean(first(risk.hardExcluded, raw.hardExcluded, analysis.hardExcluded, false));
    let level = '';
    if (/high|高/.test(explicit)) level = '高';
    else if (/medium|mid|中/.test(explicit)) level = '中';
    else if (/low|低/.test(explicit)) level = '低';
    else if (hard || (deduction != null && deduction >= 20)) level = '高';
    else if (flags.length || (deduction != null && deduction > 0)) level = '中';
    else if (deduction === 0) level = '低';
    else level = '待判定';
    return { level, flags, deduction, hard };
  }

  function normalize(raw = {}, source = '') {
    const nested = raw.ranking || raw.item || {};
    const result = raw.result || nested.result || raw.aiScore || {};
    const analysis = raw.analysis || nested.analysis || {};
    const stockRaw = raw.stock || nested.stock || raw;
    const symbol = String(first(stockRaw.symbol, raw.symbol, nested.symbol, '')).trim();
    const local = S.stocks.find(stock => stock.symbol === symbol) || {};
    const stock = { ...local, ...stockRaw, symbol, name: first(stockRaw.name, raw.name, nested.name, local.name, symbol) };
    const scoreObject = raw.aiScore && typeof raw.aiScore === 'object' ? raw.aiScore : {};
    const score = number(first(scoreObject.score, scoreObject.value, raw.score, nested.score, result.score, analysis.score, raw.aiScore));
    const confidence = number(first(scoreObject.confidence, raw.aiConfidence, raw.confidence, nested.confidence, result.confidence, analysis.confidence));
    const risk = riskInfo(raw, result, analysis);
    const reasons = cleanArray(raw.reasons, nested.reasons, analysis.reasons, result.reasons, scoreObject.reasons).map(String);
    const recommendation = first(raw.oneLineReason, raw.reason, raw.recommendationReason, nested.reason, analysis.recommendationReason, reasons[0], result.archetypes?.[0]);
    const trend = first(raw.trend, nested.trend, result.trend, analysis.trend, {});
    const scores = componentScores(raw, result, analysis);
    const group = first(raw._v19Group, raw.group, nested.group, stockRaw.group, groupKey(stock));
    const analysisDataDate = dateOnly(first(raw.analysisDataDate, raw.analysis_data_date, nested.analysisDataDate, nested.analysis_data_date, raw.dataDate, nested.dataDate, result.dataDate, analysis.dataDate, v19.rankings?.dataDate));
    const tradeDate = dateOnly(first(raw.tradeDate, raw.trade_date, nested.tradeDate, nested.trade_date, stockRaw.tradeDate, stockRaw.trade_date, stockRaw.priceDate, stockRaw.price_date, local.tradeDate, local.priceDate));
    const updateStatus = String(first(raw.updateStatus, nested.updateStatus, raw.cycleStatus, nested.cycleStatus, '')).toLowerCase();
    return {
      raw, stock, symbol, name: stock.name || symbol, group: groupKey({ ...stock, market: groupLabel(group), instrumentType: group === 'etf' ? 'ETF' : stock.instrumentType }),
      market: groupLabel(group), industry: first(stock.industry, raw.industry, nested.industry, '未分類'), score, confidence,
      scoreDelta: number(first(raw.scoreDelta, nested.scoreDelta, trend.scoreDelta, analysis.scoreDelta)),
      reason: recommendation || '資料不足，尚無可驗證的推薦原因。', reasons, risk, componentScores: scores,
      opposingSignals: cleanArray(raw.opposingSignals, nested.opposingSignals, analysis.opposingSignals, result.opposingSignals, analysis.negativeSignals).map(String),
      scoreHistory: array(first(raw.scoreHistory, nested.scoreHistory, analysis.scoreHistory, trend.history)),
      news: cleanArray(raw.news, analysis.news), related: cleanArray(raw.relatedStocks, analysis.relatedStocks),
      dataDate: analysisDataDate, analysisDataDate, tradeDate, source: source || raw._v19Source || (raw._v19Api ? 'v19 API' : '既有盤後資料'),
      updateStatus,
      degraded: hasDegradation(first(raw.degraded, nested.degraded, analysis.degraded, false)),
      completeness: first(
        raw.completenessLabel,
        analysis.completenessLabel,
        raw.scoreDimensions?.completeness?.value != null ? `資料完整度 ${fmt(raw.scoreDimensions.completeness.value, 0)}%` : null,
        analysis.scoreDimensions?.completeness?.value != null ? `資料完整度 ${fmt(analysis.scoreDimensions.completeness.value, 0)}%` : null,
        confidence != null ? `資料信心 ${fmt(confidence, 0)}%` : '部分資料'
      )
    };
  }

  function fallbackRows() {
    return S.stocks.filter(stock => stock.symbol && stock.close != null).map(stock => ({
      stock,
      result: { score: opportunityScore(stock), confidence: null, reasons: [] },
      _v19Group: groupKey(stock), _v19Source: '現有量化初篩（非完整 AI 分析）', dataDate: S.date
    }));
  }

  function allRows() {
    const base = snapshotRows();
    const fallback = base.length ? base : fallbackRows();
    if (v19.rankings) {
      const fallbackBySymbol = new Map(fallback.map(row => [String(row.stock?.symbol || row.symbol), row]));
      return apiRankingRows().map(apiRow => {
        const symbol = String(apiRow.stock?.symbol || apiRow.ranking?.symbol || apiRow.symbol || '');
        const previous = fallbackBySymbol.get(symbol) || {};
        return normalize({
          ...previous, ...apiRow, _v19Api: true, _v19Source: 'v19 API',
          stock: { ...(previous.stock || {}), ...(apiRow.stock || apiRow) },
          result: { ...(previous.result || {}), ...(apiRow.result || {}) },
          analysis: { ...(previous.analysis || {}), ...(apiRow.analysis || {}) }
        }, 'v19 API');
      }).filter(row => row.symbol);
    }
    const merged = new Map(fallback.map(row => [String(row.stock?.symbol || row.symbol), row]));
    return [...merged.values()].map(row => normalize(row)).filter(row => row.symbol);
  }

  function sourceStatus() {
    const snap = globalThis.twssUltimateSnapshot?.();
    const degraded = hasDegradation(v19.home?.degraded) || hasDegradation(v19.rankings?.degraded);
    const active = v19.home || v19.rankings;
    const groupStatuses = active?.groupStatuses && typeof active.groupStatuses === 'object' ? Object.values(active.groupStatuses) : [];
    const partial = (active?.updateStatus && active.updateStatus !== 'complete') || groupStatuses.some(status => status !== 'final');
    const groupNames = { deep_listed: '上市', deep_otc: '上櫃', deep_etf: 'ETF' };
    const progress = cleanArray(v19.home?.jobs)
      .filter(job => groupNames[job?.job])
      .map(job => `${groupNames[job.job]} ${fmt(number(job.progress) ?? 0, 0)}%`)
      .join('、');
    if (active) return {
      label: degraded
        ? 'v19 API（部分降級）'
        : partial
          ? `分析結果已可使用${progress ? `（${progress}；背景持續補齊）` : '（背景持續補齊）'}`
          : '資料分析已完成',
      cls: degraded || partial ? 'warn' : 'ok'
    };
    if (snap) return { label: '深度快照回退', cls: 'warn' };
    return { label: '盤後量化初篩', cls: 'warn' };
  }

  function scoreText(value) { return value == null ? '—' : fmt(value, 0); }
  function confidenceText(value) { return value == null ? '待深度資料' : `${fmt(value, 0)}%`; }
  function riskClass(level) { return level === '高' ? 'bad' : level === '中' || level === '待判定' ? 'warn' : ''; }

  function stockCard(row, rank = 0) {
    const watched = isWatched(row.symbol);
    return `<article class="card ultimate-card v19-stock-card ${row.source === 'v19 API' ? 'formal' : 'provisional'}">
      ${rank ? `<span class="ultimate-rank">${rank}</span>` : ''}
      <div class="head"><div><b class="smart-name">${esc(row.name)}</b><div class="muted">${esc(row.symbol)} · ${esc(row.market)} · ${esc(row.industry)}</div></div><div class="v19-score"><small>AI 分數</small><strong>${scoreText(row.score)}</strong></div></div>
      <div class="v19-card-meta"><span class="tag info">AI 信心 ${confidenceText(row.confidence)}</span><span class="tag ${riskClass(row.risk.level)}">風險 ${esc(row.risk.level)}</span>${row.scoreDelta == null ? '' : `<span class="tag ${row.scoreDelta >= 0 ? '' : 'bad'}">分數 ${pct(row.scoreDelta, 1)}</span>`}</div>
      <p class="v19-reason">${esc(row.reason)}</p>
      <div class="muted small">資料日 ${esc(row.dataDate || '待確認')} · ${esc(row.source)} · ${esc(row.completeness)}</div>
      <div class="row smart-actions"><button class="btn secondary grow" type="button" data-watch="${esc(row.symbol)}">${watched ? '✓ 已加入自選' : '＋ 加入自選'}</button><button class="btn grow" type="button" data-analysis="${esc(row.symbol)}">查看分析</button></div>
    </article>`;
  }

  function featuredStock(row) {
    if (!row) return empty('目前沒有足夠資料可產生精選。');
    const watched = isWatched(row.symbol);
    return `<article class="card v19-featured">
      <div class="v19-featured-copy"><span class="v19-eyebrow">TODAY'S PICK</span><h3>${esc(row.name)} <small>${esc(row.symbol)}</small></h3><p>${esc(row.reason)}</p><div class="v19-featured-meta"><span>信心 ${confidenceText(row.confidence)}</span><span class="${riskClass(row.risk.level)}">${esc(row.risk.level)}風險</span><span>${esc(row.market)}</span></div></div>
      <div class="v19-featured-score"><small>AI SCORE</small><strong>${scoreText(row.score)}</strong><span>/ 100</span></div>
      <div class="v19-featured-actions"><button class="btn secondary" type="button" data-watch="${esc(row.symbol)}">${watched ? '✓ 已自選' : '＋ 自選'}</button><button class="btn" type="button" data-analysis="${esc(row.symbol)}">查看分析 <span aria-hidden="true">→</span></button></div>
    </article>`;
  }

  function compactStockRow(row, rank = 0, mode = 'score') {
    const value = mode === 'riser' && row.scoreDelta != null
      ? pct(row.scoreDelta, 1)
      : mode === 'risk' ? row.risk.level : scoreText(row.score);
    const label = mode === 'riser' ? '分數變化' : mode === 'risk' ? '風險' : 'AI';
    const valueClass = mode === 'riser' ? (row.scoreDelta >= 0 ? 'up' : 'down') : mode === 'risk' ? riskClass(row.risk.level) : '';
    return `<button class="v19-compact-row" type="button" data-analysis="${esc(row.symbol)}" aria-label="查看 ${esc(row.name)} ${esc(row.symbol)} 分析">
      ${rank ? `<span class="v19-compact-rank">${rank}</span>` : ''}<span class="v19-compact-name"><b>${esc(row.name)}</b><small>${esc(row.symbol)} · ${esc(row.market)}</small></span><span class="v19-compact-value ${valueClass}"><small>${label}</small><strong>${esc(value)}</strong></span><span class="v19-row-arrow" aria-hidden="true">›</span>
    </button>`;
  }

  function empty(text) { return `<div class="card empty"><p class="muted">${esc(text)}</p></div>`; }
  function section(id, title, subtitle, body) {
    return `<section class="v19-section" data-v19-home-section="${id}" aria-labelledby="v19-${id}"><div class="v19-section-head"><div><h3 id="v19-${id}">${title}</h3>${subtitle ? `<div class="muted">${subtitle}</div>` : ''}</div></div><div class="v19-section-body">${body}</div></section>`;
  }

  function homeApiList(...keys) {
    for (const key of keys) {
      const value = v19.home?.[key];
      if (Array.isArray(value)) return value;
      if (Array.isArray(value?.items)) return value.items;
      const grouped = v19.home?.groups?.[key];
      if (Array.isArray(grouped)) return grouped;
      if (Array.isArray(grouped?.items)) return grouped.items;
    }
    return [];
  }

  function homeGroupRows() {
    const groups = v19.home?.groups;
    if (Array.isArray(groups)) return groups;
    if (!groups || typeof groups !== 'object') return [];
    const marketGroups = new Set(['listed', 'otc', 'etf', '上市', '上櫃', 'ETF']);
    const rows = Object.entries(groups).flatMap(([group, value]) => {
      const items = Array.isArray(value) ? value : array(value?.items);
      return items.map(item => marketGroups.has(group) ? { ...item, _v19Group: group } : item);
    });
    const unique = new Map();
    rows.forEach(item => {
      const symbol = String(item.stock?.symbol || item.ranking?.symbol || item.symbol || '');
      if (symbol && !unique.has(symbol)) unique.set(symbol, item);
    });
    return [...unique.values()];
  }

  function newsHtml(items, limit = 3) {
    const normalized = items.map(item => typeof item === 'string' ? { title: item } : item).filter(item => item?.title || item?.headline).slice(0, limit);
    if (!normalized.length) return empty('尚未接獲可驗證的新聞／公告資料。');
    return `<div class="card v19-news-list">${normalized.map(item => {
      const title = first(item.title, item.headline);
      const url = safeUrl(first(item.url, item.link));
      const label = url ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(title)}</a>` : `<b>${esc(title)}</b>`;
      return `<article>${label}<div class="muted small">${esc(first(item.source, item.publisher, '來源待標示'))}${first(item.publishedAt, item.date) ? ` · ${esc(dateOnly(first(item.publishedAt, item.date)) || first(item.publishedAt, item.date))}` : ''}</div>${item.summary ? `<p class="line-clamp-2">${esc(item.summary)}</p>` : ''}</article>`;
    }).join('')}</div>`;
  }

  function reportIndustries(...values){
    return cleanArray(...values).map(item=>{
      if(typeof item==='string')return{name:item,explanation:''};
      return{
        name:first(item?.industry,item?.label,item?.name,item?.title),
        explanation:first(item?.explanation,item?.summary,item?.message,'')
      }
    }).filter(item=>item.name)
  }
  function dailyReportModel(rows){
    const envelope=first(v19.dailyReport,v19.home?.dailyReport,{})||{},raw=first(envelope.report,envelope.dailyReport,envelope)||{},market=raw.market||raw.marketAnalysis||{};
    const environment=marketEnvironment(),fallbackPicks=rows.filter(row=>row.score!=null).sort((a,b)=>b.score-a.score).slice(0,3);
    const strengthRaw=first(raw.marketStrength,market.strength,raw.strength),strength=typeof strengthRaw==='object'?first(strengthRaw.label,strengthRaw.level,strengthRaw.summary,strengthRaw.explanation):strengthRaw;
    const directionRaw=first(raw.institutionalDirection,raw.institutional,market.institutionalDirection),direction=typeof directionRaw==='object'?first(directionRaw.direction,directionRaw.summary,directionRaw.explanation,directionRaw.label):directionRaw;
    const industries=reportIndustries(raw.hotIndustries,raw.industries,market.hotIndustries).slice(0,6);
    const focusRaw=cleanArray(raw.watchStocks,raw.opportunityStocks,raw.stocksToWatch,raw.opportunities);
    const focus=focusRaw.map(item=>{
      if(typeof item==='string'){const local=rows.find(row=>row.symbol===item||row.name===item);return local||{name:item,symbol:'',reason:''}}
      const symbol=String(first(item.symbol,item.stock?.symbol,'')||''),local=rows.find(row=>row.symbol===symbol),reason=first(item.whyNotice,item.reason,item.summary,item.why,'');
      return{...(local||{}),name:first(item.name,item.stock?.name,local?.name,symbol),symbol,reason}
    }).filter(item=>item.name||item.symbol).slice(0,5);
    const risks=cleanArray(raw.mainRisks,raw.risks,market.risks).map(item=>typeof item==='string'?item:[first(item?.title,item?.name,'風險提醒'),item?.explanation].filter(Boolean).join('：')).filter(Boolean).slice(0,6);
    const watch=cleanArray(raw.watchlistChanges,raw.watchlist?.items).map(item=>typeof item==='string'?item:[first(item?.name,item?.symbol),item?.status,item?.explanation].filter(Boolean).join('：')).filter(Boolean).slice(0,4);
    return{
      dataDate:dateOnly(first(envelope.dataDate,raw.dataDate,raw.reportDate,raw.date,v19.home?.dataDate,S.date)),
      oneLine:first(raw.oneLine,raw.todayMarket,raw.headline,raw.summary?.oneLine,market.oneLine,market.summary,`${environment.label}；上漲 ${environment.up} 檔、下跌 ${environment.down} 檔。`),
      strength:first(strength,environment.label),
      strengthExplanation:first(typeof strengthRaw==='object'?first(strengthRaw.explanation,strengthRaw.summary):strengthRaw,`${environment.label}，上漲家數約 ${fmt(environment.breadth,0)}%；市場仍可能隨新資料變動。`),
      institutional:first(direction,environment.inst>0?'偏買方':environment.inst<0?'偏賣方':'方向不明顯'),
      institutionalExplanation:first(typeof directionRaw==='object'?first(directionRaw.explanation,directionRaw.summary):directionRaw,environment.inst>0?'三大法人合計偏買方，但仍要觀察是否連續。':environment.inst<0?'三大法人合計偏賣方，追價前要更保守。':'法人方向不明顯，先看個股基本面。'),
      industries:industries.length?industries:environment.industries.slice(0,3).map(item=>({name:item.industry,explanation:`平均漲跌 ${pct(item.avgChange)}，上漲家數約 ${fmt(item.breadth,0)}%。`})),
      focus:focus.length?focus:fallbackPicks,
      risks,
      news:cleanArray(raw.importantNews,raw.importantNewsAndAnnouncements,raw.news,raw.announcements),
      watch,
      source:v19.dailyReport?'AI 每日報告':'現有資料快速摘要'
    }
  }

  function dailyReportHtml(rows){
    const report=dailyReportModel(rows),riskItems=report.risks.length?report.risks:['市場與個股資料仍可能更新，請避免只看單一分數。'];
    const explain=(label,value)=>value&&value!==label?`<p>${esc(value)}</p>`:'';
    const headlines=report.news.slice(0,3).map(item=>typeof item==='string'?{title:item}:item).filter(item=>item?.title||item?.headline);
    const headlineHtml=headlines.map(item=>{const title=first(item.title,item.headline),url=safeUrl(first(item.url,item.link)),source=first(item.source,item.publisher);return`<li>${url?`<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(title)}</a>`:`<b>${esc(title)}</b>`}${source?`<small>${esc(source)}</small>`:''}</li>`}).join('');
    const industryHtml=report.industries.map(item=>`<div><b>${esc(item.name)}</b>${item.explanation?`<small>${esc(item.explanation)}</small>`:''}</div>`).join('')||'<div><b>資料整理中</b></div>';
    return `<article class="card v19-daily-report"><div class="v19-report-head"><span class="v19-eyebrow">DAILY AI BRIEF</span><time>${esc(report.dataDate||'日期待確認')}</time></div><p class="v19-report-lead">${esc(report.oneLine)}</p><div class="v19-report-grid"><div><small>市場強弱</small><b>${esc(report.strength)}</b>${explain(report.strength,report.strengthExplanation)}</div><div><small>法人方向</small><b>${esc(report.institutional)}</b>${explain(report.institutional,report.institutionalExplanation)}</div></div><div class="v19-report-block"><h4>熱門產業</h4><div class="v19-report-industries">${industryHtml}</div></div><div class="v19-report-block"><h4>值得關注</h4><div class="v19-report-stocks">${report.focus.map(item=>item.symbol?`<button type="button" data-analysis="${esc(item.symbol)}"><b>${esc(item.name)}</b><small>${esc(item.symbol)}${item.reason?` · ${esc(item.reason)}`:''}</small></button>`:`<span>${esc(item.name)}</span>`).join('')||'<span>目前沒有足夠資料</span>'}</div></div><div class="v19-report-block"><h4>主要風險</h4><ul>${riskItems.map(item=>`<li>${esc(item)}</li>`).join('')}</ul></div>${headlineHtml?`<div class="v19-report-block"><h4>重要新聞與公告</h4><ul class="v19-report-news">${headlineHtml}</ul></div>`:''}${report.watch.length?`<div class="v19-report-block"><h4>自選股變化</h4><ul>${report.watch.map(item=>`<li>${esc(item)}</li>`).join('')}</ul></div>`:''}<div class="v19-report-foot">${esc(report.source)} · 新聞／公告 ${report.news.length} 則 · 自選變化 ${report.watch.length} 則</div></article>`
  }

  function homeNewsItems(){
    const report=dailyReportModel(allRows()),home=homeApiList('news','importantNews','announcements'),unique=new Map();
    [...report.news,...home].forEach(item=>{const value=typeof item==='string'?{title:item}:item,title=first(value?.title,value?.headline);if(title&&!unique.has(title))unique.set(title,value)});
    return [...unique.values()]
  }
  function newsPanel(){
    const news=homeNewsItems(),visible=Math.min(v19.newsVisible,news.length),body=newsHtml(news,visible);
    return `${body}${visible<news.length?`<button id="v19NewsMore" class="btn secondary load-more" type="button">載入更多（剩餘 ${news.length-visible} 則）</button>`:''}`
  }
  function bindNewsMore(){q('#v19NewsMore')?.addEventListener('click',()=>{v19.newsVisible+=5;const body=q('[data-v19-home-section="news"] .v19-section-body');if(body){body.innerHTML=newsPanel();bindNewsMore()}})}

  function watchChanges(rows) {
    const watched = new Set(getWatchlist().map(item => String(item.symbol)));
    const candidates = new Map(rows.map(row => [row.symbol, row]));
    v19.watchRows.forEach(row => candidates.set(row.symbol, row));
    const changed = [...candidates.values()].filter(row => watched.has(row.symbol) && row.scoreDelta != null && row.scoreDelta !== 0).sort((a, b) => Math.abs(b.scoreDelta) - Math.abs(a.scoreDelta)).slice(0, 5);
    let alerts = [];
    try {
      const stored = JSON.parse(localStorage.getItem(twssUserData.storageKey('rule-alerts')) || '[]');
      alerts = Array.isArray(stored) ? stored : array(stored?.events);
    } catch {}
    const alertRows = alerts.filter(item => watched.has(String(item.symbol))).slice(-3).reverse();
    if (!alertRows.length && !changed.length) return empty('目前沒有已驗證的重要變化；自選提醒會在資料更新後顯示。');
    const items = [
      ...alertRows.map(item => ({ symbol: item.symbol, title: `${item.name || item.symbol} ${item.symbol}`, message: first(item.message, item.title, '自選條件已觸發') })),
      ...changed.map(row => ({ symbol: row.symbol, title: `${row.name} ${row.symbol}`, message: `AI 分數 ${pct(row.scoreDelta, 1)}` })),
    ].slice(0, 3);
    return `<div class="card v19-change-list">${items.map(item => `<button type="button" data-analysis="${esc(item.symbol)}"><b>${esc(item.title)}</b><span>${esc(item.message)}</span><i aria-hidden="true">›</i></button>`).join('')}</div>`;
  }

  function marketIndexCard(item, fallback) {
    if (!item) return `<div class="v19-index-card pending"><span>${esc(fallback.name)}</span><strong>同步中</strong><small>官方盤後資料</small></div>`;
    const change = number(first(item.changePercent, item.change_pct));
    const value = number(first(item.value, item.close));
    const detail = item.code === 'tx' && item.contractMonth ? `${item.contractMonth} · 日盤` : '官方收盤';
    return `<div class="v19-index-card"><div class="v19-index-title"><span>${esc(first(item.name, fallback.name))}</span><small>${esc(detail)}</small></div><strong>${value == null ? '—' : fmt(value, 2)}</strong><b class="${cls(change)}">${change == null ? '—' : pct(change, 2)}</b><time>${esc(first(item.dataDate, item.tradeDate, '日期待確認'))}</time></div>`;
  }

  function marketSummary(rows) {
    const valid = S.stocks.filter(stock => stock.close != null);
    const up = valid.filter(stock => number(stock.change) > 0).length;
    const down = valid.filter(stock => number(stock.change) < 0).length;
    const turnover = valid.reduce((sum, stock) => sum + (number(stock.value) || 0), 0);
    const dates = marketDateInfo();
    const indexRows = array(v19.benchmarks?.marketIndices);
    const indexByCode = new Map(indexRows.map(item => [String(item.code || ''), item]));
    const expected = [{ code: 'taiex', name: '加權指數' }, { code: 'tpex', name: '櫃買指數' }, { code: 'tx', name: '台指期' }];
    return `<div class="card v19-market-summary"><div class="v19-index-strip">${expected.map(item => marketIndexCard(indexByCode.get(item.code), item)).join('')}</div><div class="v19-breadth"><span><i class="up">${fmt(up, 0)}</i> 上漲</span><span><i class="down">${fmt(down, 0)}</i> 下跌</span><span><i>${fmt(Math.max(0, valid.length - up - down), 0)}</i> 平盤</span><span class="grow"><i>${turnover ? `${fmt(turnover / 100000000, 0)} 億` : '—'}</i> 成交額</span></div><div class="v19-data-line"><span>上市 ${esc(dates.listed || '待確認')}</span><span>上櫃 ${esc(dates.otc || '待確認')}</span><span>分析 ${esc(first(v19.home?.dataDate, v19.rankings?.dataDate, rows[0]?.dataDate, '待確認'))}</span></div></div>`;
  }

  function v19HomePage() {
    const rows = allRows();
    const status = sourceStatus();
    const groupedRows = homeGroupRows().map(row => normalize({ ...row, _v19Api: true }, 'v19 API'));
    const homeRows = groupedRows.length ? groupedRows : rows;
    const apiPicks = homeApiList('todayPicks', 'picks', 'aiPicks', 'featured');
    const picks = (apiPicks.length ? apiPicks.map(row => normalize({ ...row, _v19Api: true }, 'v19 API')) : homeRows.filter(row => row.score != null).sort((a, b) => b.score - a.score)).slice(0, 3);
    const apiRisers = homeApiList('fastestRisers', 'risers', 'scoreRisers');
    const risers = (apiRisers.length ? apiRisers.map(row => normalize({ ...row, _v19Api: true }, 'v19 API')) : homeRows.filter(row => row.scoreDelta != null && row.scoreDelta > 0).sort((a, b) => b.scoreDelta - a.scoreDelta)).slice(0, 3);
    const apiRanks = homeApiList('rankings', 'topRankings', 'aiRankings');
    const rankings = (apiRanks.length ? apiRanks.map(row => normalize({ ...row, _v19Api: true }, 'v19 API')) : homeRows.filter(row => row.score != null).sort((a, b) => b.score - a.score)).slice(0, 5);
    return `<div class="v19-dashboard"><div class="v19-hero"><div><small>MARKET INTELLIGENCE</small><h2>今日重點</h2></div><span class="status-pill ${status.cls}">${esc(status.label)}</span></div>
      ${section('market', '今日市場摘要', '', marketSummary(rows))}
      ${section('daily-report','AI 每日報告','用白話整理市場、產業、法人、機會與風險。',dailyReportHtml(homeRows))}
      ${section('picks', '今日 AI 精選', '', picks.length ? `${featuredStock(picks[0])}${picks.length > 1 ? `<div class="v19-compact-list v19-pick-rest">${picks.slice(1).map((row, index) => compactStockRow(row, index + 2)).join('')}</div>` : ''}` : empty('目前沒有足夠資料可產生精選。'))}
      <div class="v19-home-grid">
        ${section('risers', '分數上升最快', '', risers.length ? `<div class="v19-compact-list">${risers.map((row, index) => compactStockRow(row, index + 1, 'riser')).join('')}</div>` : empty('目前沒有可驗證的分數變化。'))}
        ${section('ranking', 'AI 排行榜', '', rankings.length ? `<div class="v19-compact-list">${rankings.map((row, index) => compactStockRow(row, index + 1)).join('')}</div><button class="v19-text-link" type="button" data-tab-jump="opportunities">完整排行榜 <span aria-hidden="true">→</span></button>` : empty('排行榜資料整理中。'))}
      </div>
      <div class="v19-home-grid v19-secondary-grid">
        ${section('watch', '自選股重要變化', '', watchChanges(rows))}
        ${section('news', '今日重要新聞與公告', '先顯示最新內容，可逐步載入更多。', newsPanel())}
      </div>
      ${disclaimer()}</div>`;
  }

  function filteredRows() {
    if (v19.rankings) return allRows();
    const query = v19.query.trim().toLocaleLowerCase('zh-TW');
    const rows = allRows().filter(row => {
      if (v19.market !== 'all' && row.group !== v19.market) return false;
      if (v19.industry !== 'all' && row.industry !== v19.industry) return false;
      return !query || `${row.symbol} ${row.name}`.toLocaleLowerCase('zh-TW').includes(query);
    });
    const compareNumber = (a, b, key, direction = -1) => ((a[key] == null) - (b[key] == null)) || direction * ((a[key] || 0) - (b[key] || 0));
    if (v19.sort === 'score_asc') rows.sort((a, b) => compareNumber(a, b, 'score', 1));
    else if (v19.sort === 'confidence_desc') rows.sort((a, b) => compareNumber(a, b, 'confidence'));
    else if (v19.sort === 'change_desc') rows.sort((a, b) => compareNumber(a, b, 'scoreDelta'));
    else if (v19.sort === 'risk_asc' || v19.sort === 'risk_desc') {
      const order = { 低: 1, 中: 2, 高: 3, 待判定: 4 }, direction = v19.sort === 'risk_asc' ? 1 : -1;
      rows.sort((a, b) => direction * ((order[a.risk.level] || 4) - (order[b.risk.level] || 4)));
    }
    else rows.sort((a, b) => compareNumber(a, b, 'score'));
    return rows;
  }

  function v19RankingPage() {
    const all = allRows();
    const homeIndustries = cleanArray(v19.home?.filters?.industries, v19.home?.industries);
    const industries = [...new Set([...v19.rankingIndustries, ...homeIndustries, ...all.map(row => row.industry).filter(Boolean)])].sort((a, b) => String(a).localeCompare(String(b), 'zh-Hant-TW'));
    if (v19.industry !== 'all' && !industries.includes(v19.industry)) v19.industry = 'all';
    const rows = filteredRows();
    const visible = rows.slice(0, v19.visible);
    const status = sourceStatus();
    return `<div class="v19-hero v19-page-hero"><div><small>AI RANKING</small><h2>AI 排行榜</h2></div><span class="status-pill ${status.cls}">${esc(status.label)}</span></div>
      <section class="card v19-ranking-filter"><div class="search-row"><label class="sr-only" for="v19RankSearch">搜尋股票</label><input id="v19RankSearch" type="search" value="${esc(v19.query)}" placeholder="輸入代號或名稱"><button id="v19RankSearchBtn" class="btn" type="button">搜尋</button></div><div class="v19-filter-grid"><label>市場<select id="v19RankMarket"><option value="all">全部市場</option><option value="listed" ${v19.market === 'listed' ? 'selected' : ''}>上市</option><option value="otc" ${v19.market === 'otc' ? 'selected' : ''}>上櫃</option><option value="etf" ${v19.market === 'etf' ? 'selected' : ''}>ETF</option></select></label><label>產業<select id="v19RankIndustry"><option value="all">全部產業</option>${industries.map(value => `<option value="${esc(value)}" ${value === v19.industry ? 'selected' : ''}>${esc(value)}</option>`).join('')}</select></label><label>排序<select id="v19RankSort"><option value="score_desc" ${v19.sort === 'score_desc' ? 'selected' : ''}>AI 分數高至低</option><option value="score_asc" ${v19.sort === 'score_asc' ? 'selected' : ''}>AI 分數低至高</option><option value="risk_asc" ${v19.sort === 'risk_asc' ? 'selected' : ''}>風險低至高</option><option value="risk_desc" ${v19.sort === 'risk_desc' ? 'selected' : ''}>風險高至低</option><option value="change_desc" ${v19.sort === 'change_desc' ? 'selected' : ''}>分數升幅</option><option value="confidence_desc" ${v19.sort === 'confidence_desc' ? 'selected' : ''}>AI 信心</option></select></label></div></section>
      <div class="smart-results-head"><div><h3>篩選結果</h3><div class="muted">共 ${rows.length} 檔，現在顯示 ${visible.length} 檔</div></div><b>${esc(first(v19.rankings?.dataDate, visible[0]?.dataDate, S.date, '日期待確認'))}</b></div>
      ${visible.length ? `<div class="list ultimate-results v19-rank-results">${visible.map((row, index) => stockCard(row, index + 1)).join('')}</div>${visible.length < rows.length || v19.rankingNextCursor ? `<button id="v19RankMore" class="btn secondary load-more" type="button" ${v19.rankingLoading ? 'disabled' : ''}>${v19.rankingLoading ? '載入中…' : '再顯示 20 檔'}</button>` : ''}` : empty(v19.rankingLoading ? '正在讀取排行榜…' : '沒有符合搜尋與篩選條件的標的。')}
      ${disclaimer()}`;
  }

  function detailList(items, none, className = '') {
    const values = cleanArray(items).map(item => typeof item === 'string' ? item : first(item.label, item.title, item.message, item.reason)).filter(Boolean);
    return values.length ? `<ul class="v19-detail-list ${className}">${values.slice(0, 12).map(value => `<li>${esc(value)}</li>`).join('')}</ul>` : `<p class="muted">${esc(none)}</p>`;
  }

  function detailNews(items) {
    const rows = cleanArray(items).map(item => typeof item === 'string' ? { title: item } : item).filter(item => item?.title || item?.headline);
    if (!rows.length) return empty('目前沒有從 v19 API 取得可驗證的個股新聞／公告。');
    return `<div class="card v19-news-list">${rows.slice(0, 12).map(item => {
      const title = first(item.title, item.headline), url = safeUrl(first(item.url, item.link));
      return `<article>${url ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(title)}</a>` : `<b>${esc(title)}</b>`}<div class="muted small">${esc(first(item.source, item.publisher, '來源待標示'))}${first(item.publishedAt, item.date) ? ` · ${esc(dateOnly(first(item.publishedAt, item.date)) || first(item.publishedAt, item.date))}` : ''}</div>${item.summary ? `<p>${esc(item.summary)}</p>` : ''}</article>`;
    }).join('')}</div>`;
  }

  function scoreHistoryHtml(row) {
    const history = row.scoreHistory.map((item, index) => typeof item === 'number' ? { score: item, index } : item).map(item => ({
      date: dateOnly(first(item.date, item.dataDate, item.at)) || `紀錄 ${Number(item.index ?? 0) + 1}`,
      score: number(first(item.score, item.value, item.aiScore)), rank: number(first(item.rank, item.position))
    })).filter(item => item.score != null);
    if (!history.length) return empty('分數歷史仍在累積；至少兩個不同資料日後才顯示變化。');
    return `<div class="card table-wrap"><table><thead><tr><th>資料日</th><th>AI 分數</th><th>排名</th></tr></thead><tbody>${history.slice(-12).reverse().map(item => `<tr><td>${esc(item.date)}</td><td>${scoreText(item.score)}</td><td>${item.rank == null ? '—' : `第 ${fmt(item.rank, 0)} 名`}</td></tr>`).join('')}</tbody></table></div>`;
  }

  function relatedHtml(row) {
    let rows = row.related.map(item => typeof item === 'string' ? allRows().find(candidate => candidate.symbol === item) : normalize(item, 'v19 API')).filter(Boolean).filter(item => item.symbol && item.symbol !== row.symbol);
    let fallback = false;
    if (!rows.length) {
      fallback = true;
      rows = allRows().filter(item => item.symbol !== row.symbol && item.industry === row.industry && item.group === row.group).sort((a, b) => (b.score || 0) - (a.score || 0)).slice(0, 5);
    }
    if (!rows.length) return empty('目前沒有足夠的同產業標的可供參考。');
    return `<div class="card"><div class="muted small">${fallback ? '同產業參考（非 AI 關聯判定）' : 'v19 API 關聯標的'}</div><div class="v19-related">${rows.slice(0, 6).map(item => `<button type="button" data-v19-related="${esc(item.symbol)}"><span><b>${esc(item.name)}</b><small>${esc(item.symbol)} · ${esc(item.industry)}</small></span><strong>${scoreText(item.score)}</strong></button>`).join('')}</div></div>`;
  }

  function beginnerExplanation(row,indicators){
    const stock=row.stock,isEtf=row.group==='etf';
    const technical=!indicators?'價格歷史仍在補齊，現在不適合只看技術指標下結論。':stock.close>indicators.ma20?`目前收盤高於近 20 日平均，代表短期買方較有力；但仍要留意是否跌回平均線下方。`:`目前收盤未站上近 20 日平均，短期走勢較弱，先觀察是否止跌與成交量回穩。`;
    const fundamental=isEtf?'ETF 是一籃子資產，不用單一公司的營收或本益比判斷；更應留意成交量、追蹤標的與波動。':stock.rev==null?'公司最新營收成長資料尚未補齊，先不要把資料空白解讀成表現差。':stock.rev>=10?`最新月營收比去年同期成長 ${fmt(stock.rev,1)}%，代表業務動能有改善；仍要確認獲利是否同步。`:stock.rev<0?`最新月營收比去年同期減少 ${fmt(Math.abs(stock.rev),1)}%，成長動能偏弱，需要追蹤後續月份。`:`最新月營收年增 ${fmt(stock.rev,1)}%，成長幅度不大，宜搭配獲利與產業狀況判斷。`;
    const institutional=stock.inst==null?'法人買賣資料尚未補齊，不能據此判斷資金方向。':stock.inst>0?`三大法人合計買超 ${fmt(stock.inst,0)} 張，當日資金偏買方；單日買超不等於長期趨勢。`:stock.inst<0?`三大法人合計賣超 ${fmt(Math.abs(stock.inst),0)} 張，當日資金偏賣方，短線要更保守。`:'三大法人買賣大致平衡，當日沒有明顯資金方向。';
    const strengths=[];if(row.score!=null&&row.score>=75)strengths.push(`AI 綜合分數 ${fmt(row.score,0)}，目前位於較值得優先研究的區間`);if(stock.rev>=10)strengths.push('營收較去年同期成長');if(stock.inst>0)strengths.push('法人當日合計買超');if(!strengths.length)strengths.push('目前沒有足夠資料確認明顯優勢，先列入觀察');
    const riskText=row.risk.flags[0]||row.opposingSignals[0]||(stock.debt>=70?'負債比偏高，財務彈性較小':stock.pe>=35?'目前價格相對獲利偏高，估值風險較大':'資料與市場狀況仍會改變，不能只依單一分數決定');
    return{why:row.reason||'資料仍在整理，暫時沒有足夠理由提高研究優先順序。',strengths:strengths.join('；')+'。',risk:riskText,technical,fundamental,institutional}
  }

  function v19DetailHtml(row, detailState) {
    const stock = row.stock;
    const indicators = detailState.history?.indicators || null;
    const components = row.componentScores;
    const plain=beginnerExplanation(row,indicators);
    const recommendationReasons = row.reasons.length ? row.reasons : [row.reason];
    const opposing = row.opposingSignals;
    const risks = [...new Set(row.risk.flags)];
    const partial = row.updateStatus && !['complete', 'final'].includes(row.updateStatus);
    const dataState = detailState.loading ? '載入 v19 詳細資料中' : row.degraded ? 'v19 部分降級' : partial ? '目前分析已可使用（背景持續補齊）' : row.source;
    return `<div class="modal"><div class="sheet v19-detail-sheet"><button class="sheet-close" type="button">×</button>
      <div class="v19-detail-hero"><div><span class="tag info">${esc(dataState)}</span><h2>${esc(row.name)} ${esc(row.symbol)}</h2><div class="muted">${esc(row.market)} · ${esc(row.industry)}</div></div><button class="btn secondary small-btn" type="button" data-watch="${esc(row.symbol)}">${isWatched(row.symbol) ? '✓ 已加入自選' : '＋ 加入自選'}</button></div>
      <section aria-labelledby="v19-quote"><h3 id="v19-quote" class="section-title">最新報價與資料日期</h3><div class="card accent"><div class="head"><div><small class="muted">最新收盤</small><div class="price">${fmt(stock.close)} 元</div><b class="${cls(stock.change)}">${pct(stock.change)}</b></div><div class="v19-score"><small>AI 分數</small><strong>${scoreText(row.score)}</strong><span>信心 ${confidenceText(row.confidence)}</span></div></div><div class="grid four v19-quote-grid">${metric('開盤', fmt(stock.open))}${metric('最高', fmt(stock.high))}${metric('最低', fmt(stock.low))}${metric('成交量', stock.volume == null ? '—' : `${fmt(stock.volume, 0)} 張`)}</div><div class="v19-data-line"><span>行情日 ${esc(row.tradeDate || '待確認')}</span><span>分析日 ${esc(row.analysisDataDate || '待確認')}</span><span>${esc(row.source)}</span><span>${esc(row.completeness)}</span></div></div></section>
      <section aria-labelledby="v19-beginner"><h3 id="v19-beginner" class="section-title">三分鐘看懂</h3><div class="card v19-beginner"><div><small>為什麼值得注意</small><p>${esc(plain.why)}</p></div><div><small>有什麼優點</small><p>${esc(plain.strengths)}</p></div><div><small>有什麼風險</small><p>${esc(plain.risk)}</p></div></div></section>
      <section aria-labelledby="v19-scores"><h3 id="v19-scores" class="section-title">綜合與分項分數</h3><div class="card"><div class="grid three">${metric('綜合 AI 分數', scoreText(row.score))}${metric('AI 信心', confidenceText(row.confidence))}${metric('分數變化', row.scoreDelta == null ? '資料累積中' : pct(row.scoreDelta, 1))}</div>${components.length?`<div class="v19-components">${components.map(item => `<div><span>${esc(item.label)}</span><b class="${cls(item.score)}">${item.score > 0 ? '+' : ''}${fmt(item.score, 1)}${item.max ? ` / ${fmt(item.max, 0)}` : ''}</b></div>`).join('')}</div>`:'<p class="muted small">分項資料尚未回傳；先看上方白話重點，不顯示推估數字。</p>'}</div></section>
      <section aria-labelledby="v19-reason"><h3 id="v19-reason" class="section-title">推薦原因</h3><div class="card"><p class="v19-lead">${esc(row.reason)}</p>${detailList(recommendationReasons, '目前沒有更多可驗證的支持因素。')}</div></section>
      <section aria-labelledby="v19-opposing"><h3 id="v19-opposing" class="section-title">對立訊號</h3><div class="card">${detailList(opposing, '目前沒有已驗證的對立訊號；不代表沒有風險。', 'warning')}</div></section>
      <section aria-labelledby="v19-risk"><h3 id="v19-risk" class="section-title">風險警示</h3><div class="card ${row.risk.level === '高' ? 'error-card' : row.risk.level === '中' ? 'warn-card' : ''}"><span class="tag ${riskClass(row.risk.level)}">風險等級 ${esc(row.risk.level)}</span>${detailList(risks, row.risk.level === '待判定' ? '風險資料不足，請勿解讀為低風險。' : '目前沒有額外結構化風險旗標。', 'warning')}</div></section>
      <section aria-labelledby="v19-technical"><h3 id="v19-technical" class="section-title">技術面</h3>${detailState.loading && !indicators ? '<div class="card"><div class="loading"><span class="spinner"></span>正在取得歷史日線…</div></div>' : `<div class="card v19-explained"><p><b>白話解讀：</b>${esc(plain.technical)}</p><div class="grid three">${metric('MA5', fmt(indicators?.ma5))}${metric('MA20', fmt(indicators?.ma20))}${metric('MA60', fmt(indicators?.ma60))}${metric('RSI 14', fmt(indicators?.rsi14))}${metric('MACD', fmt(indicators?.macd))}${metric('20 日動能', indicators?.momentum20 == null ? '—' : pct(indicators.momentum20))}${metric('量能比 5/20', indicators?.volumeRatio == null ? '—' : `${fmt(indicators.volumeRatio)} 倍`)}${metric('ATR 波動', indicators?.atrPct == null ? '—' : `${fmt(indicators.atrPct)}%`)}${metric('歷史筆數', indicators?.rows == null ? '—' : fmt(indicators.rows, 0))}</div></div>`}${detailState.historyError ? `<div class="notice">歷史日線暫時無法取得：${esc(detailState.historyError)}</div>` : ''}</section>
      <section aria-labelledby="v19-fundamental"><h3 id="v19-fundamental" class="section-title">基本面</h3><div class="card v19-explained"><p><b>白話解讀：</b>${esc(plain.fundamental)}</p><div class="grid three">${metric('月營收年增', stock.rev == null ? '—' : pct(stock.rev))}${metric('月營收月增', stock.revMom == null ? '—' : pct(stock.revMom))}${metric('EPS', fmt(stock.eps))}${metric('ROE', stock.roe == null ? '—' : `${fmt(stock.roe)}%`)}${metric('本益比', fmt(stock.pe))}${metric('股價淨值比', fmt(stock.pb))}${metric('殖利率', stock.yield == null ? '—' : `${fmt(stock.yield)}%`)}${metric('營業利益率', stock.operatingMargin == null ? '—' : `${fmt(stock.operatingMargin)}%`)}${metric('負債比', stock.debt == null ? '—' : `${fmt(stock.debt)}%`)}</div></div></section>
      <section aria-labelledby="v19-institutional"><h3 id="v19-institutional" class="section-title">法人籌碼</h3><div class="card v19-explained"><p><b>白話解讀：</b>${esc(plain.institutional)}</p><div class="grid three">${metric('外資', stock.foreign == null ? '—' : `${fmt(stock.foreign, 0)} 張`)}${metric('投信', stock.trust == null ? '—' : `${fmt(stock.trust, 0)} 張`)}${metric('自營商', stock.dealer == null ? '—' : `${fmt(stock.dealer, 0)} 張`)}${metric('三大法人', stock.inst == null ? '—' : `${fmt(stock.inst, 0)} 張`)}${metric('融資增減', stock.marginChange == null ? '—' : `${fmt(stock.marginChange, 0)} 張`)}${metric('融券增減', stock.shortChange == null ? '—' : `${fmt(stock.shortChange, 0)} 張`)}</div></div></section>
      <section aria-labelledby="v19-news"><h3 id="v19-news" class="section-title">新聞與公告</h3>${detailNews(row.news)}</section>
      <section aria-labelledby="v19-history"><h3 id="v19-history" class="section-title">分數歷史</h3>${scoreHistoryHtml(row)}</section>
      <section aria-labelledby="v19-related"><h3 id="v19-related" class="section-title">相關股票</h3>${relatedHtml(row)}</section>
      ${disclaimer()}
    </div></div>`;
  }

  async function openV19Detail(symbol) {
    const stock = S.stocks.find(item => item.symbol === symbol);
    if (!stock) return;
    S.detailSymbol = symbol;
    let row = allRows().find(item => item.symbol === symbol) || normalize({ stock, _v19Source: '現有盤後資料' });
    const state = { loading: true, history: null, historyError: '' };
    const paint = () => {
      if (S.detailSymbol !== symbol) return;
      const scroll = q('.sheet', modalRoot)?.scrollTop || 0;
      modalRoot.innerHTML = v19DetailHtml(row, state);
      bindModal();
      qa('[data-v19-related]', modalRoot).forEach(button => button.onclick = () => openV19Detail(button.dataset.v19Related));
      const sheet = q('.sheet', modalRoot); if (sheet) sheet.scrollTop = scroll;
    };
    paint();
    const [detailResult, historyResult, deepResult] = await Promise.allSettled([
      optionalJson(`/stocks?symbol=${encodeURIComponent(symbol)}`),
      getHistory(symbol),
      getDeepAnalysis(symbol)
    ]);
    if (S.detailSymbol !== symbol) return;
    const detail = detailResult.status === 'fulfilled' ? detailResult.value : null;
    const deep = deepResult.status === 'fulfilled' ? deepResult.value : null;
    if (detail || deep) {
      row = normalize({
        ...row.raw, ...(deep || {}), ...(detail || {}), _v19Api: Boolean(detail), _v19Source: detail ? 'v19 API' : row.source,
        stock: { ...stock, ...(row.raw.stock || {}), ...(deep?.stock || {}), ...(detail?.stock || {}) },
        ranking: { ...(row.raw.ranking || {}), ...(detail?.ranking || {}) },
        analysis: { ...(row.raw.analysis || {}), ...(deep?.analysis || deep || {}), ...(detail?.analysis || {}) },
        news: first(detail?.news, deep?.news, row.news), dataDate: first(detail?.dataDate, row.dataDate)
      }, detail ? 'v19 API' : row.source);
    }
    if (historyResult.status === 'fulfilled') state.history = historyResult.value;
    else state.historyError = historyResult.reason?.message || '歷史行情服務暫時不可用';
    state.loading = false;
    paint();
  }

  const v20ShellActive = Boolean(document.querySelector('script[src^="/v20.js"]'));

  async function loadV19() {
    // The v20 shell reads only its immutable recommendation publication. Do
    // not start the mutable v19 benchmark/home/detail loaders in that shell.
    if (v20ShellActive) return;
    void optionalMarketJson().then(value => {
      v19.benchmarks = value;
      globalThis.twssV19Benchmarks = value;
      if (!S.loading && S.tab === 'home') render();
    });
    const applyDailyReport=(value,state)=>{const report=unwrap(value);if(!report||typeof report!=='object')return false;v19.dailyReport=report;v19.dailyReportState=state;writeDailyReportCache(report);if(!S.loading&&S.tab==='home')render();return true};
    void fetch('/data/daily-report.json',{cache:'force-cache'}).then(response=>response.ok?response.json():null).then(value=>applyDailyReport(unwrap(value),'static')).catch(()=>{});
    const watchlist=getWatchlist().map(item=>String(item.symbol||'')).filter(Boolean).slice(0,30),reportQuery=watchlist.length?`?watchlist=${encodeURIComponent(watchlist.join(','))}`:'';
    void optionalJson(`/daily-report${reportQuery}`).then(value=>{if(!applyDailyReport(value,'ready'))v19.dailyReportState=v19.dailyReport?'cached':'fallback'});
    const homePromise=optionalJson('/home').then(value=>{v19.home=value;if(value&&!S.loading&&S.tab==='home')render();return value});
    const rankingsPromise=optionalJson(rankingQuery(10)).then(value=>{applyRankingPage(value,false);if(value&&!S.loading)render();return value});
    const [home, rankings] = await Promise.all([homePromise,rankingsPromise]);
    if (!home && !rankings) await globalThis.twssLoadUltimateSnapshot?.();
    v19.state = home || rankings ? 'ready' : 'fallback';
    if (!S.loading) render();
    loadWatchRows();
  }

  async function loadWatchRows() {
    if (v20ShellActive) return;
    const symbols = [...new Set(getWatchlist().map(item => String(item.symbol || '')).filter(Boolean))].slice(0, 20);
    const fingerprint = symbols.join(',');
    if (fingerprint === v19.watchFingerprint) return;
    v19.watchFingerprint = fingerprint;
    const generation = ++v19.watchGeneration;
    if (!symbols.length) { v19.watchRows = []; return; }
    const settled = [];
    for (let index = 0; index < symbols.length; index += 4) {
      const batch = symbols.slice(index, index + 4).map(symbol => optionalJson(`/stocks?symbol=${encodeURIComponent(symbol)}`));
      settled.push(...await Promise.allSettled(batch));
      if (generation !== v19.watchGeneration) return;
    }
    if (generation !== v19.watchGeneration) return;
    v19.watchRows = settled.flatMap((result, index) => {
      if (result.status !== 'fulfilled' || !result.value) return [];
      const symbol = symbols[index];
      const local = S.stocks.find(stock => stock.symbol === symbol) || {};
      return [normalize({ ...result.value, _v19Api: true, stock: { ...local, ...(result.value.stock || {}) } }, 'v19 API')];
    }).filter(row => row.symbol);
    if (!S.loading && S.tab === 'home') render();
  }

  const oldBind19 = bind;
  bind = function () {
    oldBind19();
    enforceDarkMode();
    bindNewsMore();
    q('[data-tab-jump="opportunities"]')?.addEventListener('click', () => navigateToTab('opportunities'));
    const search = q('#v19RankSearch');
    if (search) {
      search.oninput = event => { v19.query = event.target.value; };
      search.onkeydown = event => { if (event.key === 'Enter') { v19.query = event.target.value; reloadRankings(); } };
    }
    q('#v19RankSearchBtn')?.addEventListener('click', () => { v19.query = q('#v19RankSearch')?.value || ''; reloadRankings(); });
    q('#v19RankMarket')?.addEventListener('change', event => { v19.market = event.target.value; v19.industry = 'all'; reloadRankings(); });
    q('#v19RankIndustry')?.addEventListener('change', event => { v19.industry = event.target.value; reloadRankings(); });
    q('#v19RankSort')?.addEventListener('change', event => { v19.sort = event.target.value; reloadRankings(); });
    q('#v19RankMore')?.addEventListener('click', showMoreRankings);
    loadWatchRows();
  };

  homePage = v19HomePage;
  opportunitiesPage = v19RankingPage;
  openDetail = openV19Detail;
  const nav = q('.bottom-nav [data-tab="opportunities"]');
  if (nav) nav.innerHTML = '<span>◆</span>排行';
  enforceDarkMode();
  loadV19();
})();
