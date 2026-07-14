(() => {
  'use strict';

  const VERSION = 'v16.1 ULTIMATE';
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

  const finite = value => value != null && Number.isFinite(Number(value));
  const snapshotRows = group => Array.isArray(snapshot?.groups?.[group]) ? snapshot.groups[group] : [];
  const stockGroup = stock => stock.instrumentType === 'ETF' || /^00\d{2,4}$/.test(stock.symbol) ? 'etf' : stock.market === '上櫃' ? 'otc' : 'listed';
  const liveGroupRows = group => S.stocks.filter(stock => stockGroup(stock) === group);

  function ageLabel() {
    if (!snapshot?.generatedAt) return '尚未建立每日深度快照';
    const hours = (Date.now() - new Date(snapshot.generatedAt).getTime()) / 3600000;
    if (hours < 1) return '剛完成深度驗證';
    if (hours < 36) return `${Math.floor(hours)} 小時前完成深度驗證`;
    return `快照已 ${Math.floor(hours / 24)} 天，請執行每日更新`;
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
    });
  }

  function categoryBars(result) {
    if (!result.categories?.length) return '<div class="muted small">歷史深度資料尚未完成，因此不顯示假精準的分項分數。</div>';
    return `<div class="ultimate-factors">${result.categories.map(category => `<div class="ultimate-factor"><span>${esc(category.label)}</span><div><i style="width:${category.score ?? 0}%"></i></div><b>${category.score == null ? '—' : fmt(category.score, 0)}</b><small>${fmt(category.coverage, 0)}%</small></div>`).join('')}</div>`;
  }

  function companyMetrics(row) {
    const revenue = row.analysis?.revenue || {};
    const financial = row.analysis?.financial || {};
    const chip = row.analysis?.institutional || {};
    const price = row.analysis?.price || {};
    return `${metric('3 月平均營收年增', finite(revenue.avg3Yoy) ? pct(revenue.avg3Yoy) : reasonDash('歷史不足'), revenue.period || '')}
      ${metric('營收加速度', finite(revenue.acceleration3) ? pct(revenue.acceleration3) : reasonDash('歷史不足'), revenue.consecutiveAcceleration ? `連升 ${revenue.consecutiveAcceleration} 期` : '')}
      ${metric('20 日法人買賣超', finite(chip.inst20) ? `${fmt(chip.inst20, 0)} 張` : reasonDash('歷史不足'), finite(chip.intensity5) ? `近 5 日占量 ${fmt(chip.intensity5, 1)}%` : '')}
      ${metric('20 日相對大盤', finite(price.relative20) ? pct(price.relative20) : reasonDash('指數或價格不足'))}
      ${metric('營業利益率', finite(financial.operatingMargin) ? `${fmt(financial.operatingMargin)}%` : reasonDash('財報不足'), finite(financial.operatingMarginYoyChange) ? `年變化 ${pct(financial.operatingMarginYoyChange)}` : '')}
      ${metric('近四季現金轉換', finite(financial.cashConversion) ? `${fmt(financial.cashConversion)} 倍` : reasonDash('現金流不足'), finite(financial.ttmOperatingCashFlow) ? `TTM 營業現金流 ${fmt(financial.ttmOperatingCashFlow / 100000000)} 億` : financial.cashConversionBasis === 'latest-quarter' ? '近四季不足，暫用最新季' : 'TTM 平滑單季營運資金波動')}`;
  }

  function etfMetrics(row) {
    const price = row.analysis?.price || {};
    const etf = row.analysis?.etf || {};
    return `${metric('20 日動能', finite(price.return20) ? pct(price.return20) : reasonDash('歷史不足'))}
      ${metric('相對市場', finite(price.relative20) ? pct(price.relative20) : reasonDash('指數不足'))}
      ${metric('5／20 日量能比', finite(price.volumeRatio) ? `${fmt(price.volumeRatio)} 倍` : reasonDash('歷史不足'))}
      ${metric('ATR 波動', finite(price.atrPct) ? `${fmt(price.atrPct)}%` : reasonDash('歷史不足'))}
      ${metric('追蹤指數', etf.benchmark ? esc(etf.benchmark) : reasonDash('基金資料不足'))}
      ${metric('基金結構', etf.leveraged ? '槓桿型' : etf.inverse ? '反向型' : etf.fundType ? '一般型' : reasonDash('未辨識'))}`;
  }

  function opportunityCard(row, rank) {
    const { stock, result } = row;
    const formal = result.official;
    const missing = result.missing || [];
    const risks = [...(result.risk?.hardReasons || []), ...(result.risk?.flags || [])];
    const category = result.categories?.slice().sort((a, b) => (b.score ?? -1) - (a.score ?? -1))[0];
    return `<article class="card ultimate-card ${formal ? 'formal' : 'provisional'}">
      <div class="ultimate-rank">${rank}</div>
      <div class="head"><div><div class="row wrap"><b class="smart-name">${esc(stock.name)}</b><span class="tag ${formal ? '' : 'warn'}">${formal ? '正式候選' : '驗證／信心未達標'}</span></div><div class="muted">${stock.symbol} · ${esc(groupLabels[selectedGroup])}${stock.industry ? ` · ${esc(stock.industry)}` : ''}</div></div><div class="smart-score"><small>最終分數</small><strong>${finite(result.score) ? result.score : '—'}</strong></div></div>
      <div class="smart-price"><span class="price">${fmt(stock.close)}</span><b class="${cls(stock.change)}">${pct(stock.change)}</b></div>
      <div class="rules smart-reasons">${(result.archetypes || []).map(value => `<span>${esc(value)}</span>`).join('')}${(result.reasons || []).slice(0, 3).map(value => `<span>${esc(value)}</span>`).join('')}</div>
      <div class="grid three ultimate-metrics">${selectedGroup === 'etf' ? etfMetrics(row) : companyMetrics(row)}</div>
      ${categoryBars(result)}
      <div class="ultimate-confidence"><div><span>資料信心</span><b>${result.confidence}%</b></div><div class="progress"><span style="width:${result.confidence}%"></span></div><small>${esc(result.tier || '')}${category ? ` · 最強項 ${esc(category.label)}` : ''}</small></div>
      ${risks.length ? `<div class="ultimate-risk"><b>風險扣分 ${result.risk?.deduction || 0}</b>：${risks.map(esc).join('、')}</div>` : ''}
      <details class="ultimate-missing"><summary>資料缺漏 ${missing.length} 項</summary><div>${missing.length ? missing.map(value => `<span>${esc(value)}</span>`).join('') : '<span>核心欄位完整</span>'}</div></details>
      <div class="row smart-actions"><button class="btn grow" data-forecast="${stock.symbol}">深度趨勢頁</button><button class="btn secondary" data-watch="${stock.symbol}">${isWatched(stock.symbol) ? '★ 已自選' : '＋自選'}</button></div>
    </article>`;
  }

  function backtestPanel() {
    const data = backtest || snapshot?.backtest;
    if (!data || data.status !== 'ready') {
      return `<section class="card"><div class="head"><div><h3>點時回測</h3><div class="muted">只使用當時已公開資料，不倒填未來財報。</div></div><span class="tag warn">累積中</span></div><p class="muted">${esc(data?.message || '每日快照開始累積後，至少 25 個交易日才公布結果。')} ${finite(data?.snapshotCount) ? `目前 ${data.snapshotCount} 份。` : ''}</p></section>`;
    }
    const horizon = data.horizons?.['20'] || data.horizons?.[20] || {};
    return `<section class="card"><div class="head"><div><h3>點時回測</h3><div class="muted">排名前 10 · 不偷看未來 · 已累積 ${data.snapshotCount} 個交易日</div></div><span class="tag">可檢驗</span></div><div class="grid four">${metric('20 日平均報酬', pct(horizon.averageReturn))}${metric('20 日超額報酬', pct(horizon.averageExcessReturn))}${metric('20 日勝率', finite(horizon.winRate) ? `${fmt(horizon.winRate)}%` : '—')}${metric('平均最大回撤', pct(horizon.averageMae))}</div></section>`;
  }

  opportunitiesPage = function () {
    const deepRows = snapshotRows(selectedGroup);
    const all = deepRows.length ? deepRows : provisionalRows(selectedGroup);
    const industries = ['全部產業', ...new Set(all.map(row => row.stock.industry).filter(Boolean))];
    if (!industries.includes(selectedIndustry)) selectedIndustry = '全部產業';
    const rows = currentRows();
    const counts = Object.fromEntries(Object.keys(groupLabels).map(group => [group, S.stocks.filter(stock => stockGroup(stock) === group).length]));
    const formalCount = deepRows.filter(row => row.result?.official).length;
    const stateClass = snapshotState === 'ready' ? 'ok' : snapshotState === 'error' ? 'bad' : 'warn';
    return `<div class="smart-hero"><div><small>OPPORTUNITY ENGINE · ${VERSION}</small><h2>終極機會股</h2><p>先排除風險，再確認營運成長、法人資金、價量位置與估值；目標觀察期間為未來 1～8 週。</p></div><span class="status-pill ${stateClass}">${snapshotState === 'ready' ? '深度快照已載入' : snapshotState === 'error' ? '目前使用快照初篩' : '正在讀取深度快照'}</span></div>
      ${statusCard()}
      <section class="card ultimate-policy"><div class="head"><div><h3>四階段決策</h3><div class="muted">風險排除 → 成長確認 → 籌碼確認 → 價量進場判斷</div></div><span class="tag info">${esc(ageLabel())}</span></div><div class="ultimate-pipeline"><span>硬性排除</span><i>→</i><span>成長 30</span><i>→</i><span>籌碼 25</span><i>→</i><span>價量 25</span><i>→</i><span>估值 10</span><i>→</i><span>環境 10</span></div><p class="muted">缺漏項目會移除權重並重正規化；資料信心低於 70% 不進正式榜。風險最高扣 30 分，交易限制與價格未還原直接排除。</p></section>
      <section class="card smart-filter-card"><div class="head"><div><h3>獨立排行榜</h3><div class="muted">${groupNotes[selectedGroup]}</div></div><button id="ultimateRefresh" class="btn secondary">重新讀取</button></div><div class="smart-groups">${Object.entries(groupLabels).map(([group, label]) => `<button data-ultimate-group="${group}" class="${selectedGroup === group ? 'active' : ''}">${label}<small>${counts[group] || 0}</small></button>`).join('')}</div><div class="ultimate-controls"><label>榜單<select id="ultimateOfficial"><option value="official" ${officialOnly ? 'selected' : ''}>只看正式候選</option><option value="all" ${!officialOnly ? 'selected' : ''}>含驗證中候選</option></select></label><label>最低分數<input id="ultimateMinScore" type="number" min="0" max="100" value="${minimumScore}"></label>${selectedGroup === 'etf' ? '' : `<label>產業<select id="ultimateIndustry">${industries.map(value => `<option ${value === selectedIndustry ? 'selected' : ''}>${esc(value)}</option>`).join('')}</select></label>`}</div></section>
      <div class="smart-results-head"><div><h3>${groupLabels[selectedGroup]}正式排序</h3><div class="muted">深度驗證 ${deepRows.length} 檔 · 信心達標 ${formalCount} 檔 · 顯示 ${rows.length} 檔</div></div><b>${snapshot?.dataDate || S.date || '日期核對中'}</b></div>
      ${rows.length ? `<div class="list ultimate-results">${rows.map((row, index) => opportunityCard(row, index + 1)).join('')}</div>` : `<div class="card empty"><h3>目前沒有符合正式門檻的標的</h3><p class="muted">這不是錯誤：可能是資料信心未滿 70%、分數低於 ${minimumScore}，或所有候選被風險規則排除。可切換「含驗證中候選」查看原因。</p></div>`}
      ${backtestPanel()}
      <div class="notice"><b>重要限制</b><br>ETF 的即時淨值折溢價、追蹤誤差、內扣費用與成分集中度若無穩定公開介面，系統會明列缺漏並降低信心，不會拿公司月營收或 ROE 代替。集保資料為每週資料，不當成每日訊號。</div>
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
  }

  async function loadSnapshot(force = false) {
    snapshotState = 'loading';
    if (S.tab === 'opportunities') render();
    try {
      const response = await fetch(`/data/latest.json?${force ? Date.now() : 'v=16'}`, { cache: 'no-store' });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      if (!payload.generatedAt || !payload.groups) throw new Error(payload.message || '每日快照尚未建立');
      snapshot = payload;
      snapshotState = 'ready';
    } catch {
      snapshotState = 'error';
      snapshot = null;
    }
    // Backtest is rebuilt after the daily snapshot, so it must be read from its
    // own file instead of trusting the older copy embedded in latest.json.
    try {
      const response = await fetch(`/data/backtest.json?${force ? Date.now() : 'v=16'}`, { cache: 'no-store' });
      if (response.ok) backtest = await response.json();
    } catch {}
    if (S.tab === 'opportunities') render();
  }

  globalThis.twssUltimateSnapshot = () => snapshot;
  const oldBind = bind;
  bind = function () { oldBind(); bindUltimate(); };
  const button = q('.bottom-nav [data-tab="opportunities"]');
  if (button) button.innerHTML = '<span>◆</span>終極選股';
  loadSnapshot();
})();
