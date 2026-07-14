(() => {
  'use strict';
  const PATCH_VERSION = 'v16.3';
  const PREDICTION_KEY = 'twss-predictions-v15';
  const JOURNAL_KEY = 'twss-journal-v15';
  const patchState = { verifyQuery: '', mineTab: 'watch', backtestCache: new Map() };
  const localRead = (key, fallback = []) => { try { return JSON.parse(localStorage.getItem(key) || JSON.stringify(fallback)); } catch { return fallback; } };
  const localWrite = (key, value) => localStorage.setItem(key, JSON.stringify(value));
  const getPredictionLogs = () => localRead(PREDICTION_KEY, []);
  const setPredictionLogs = value => localWrite(PREDICTION_KEY, value);
  const getJournal = () => localRead(JOURNAL_KEY, []);
  const setJournal = value => localWrite(JOURNAL_KEY, value);
  const createId = () => crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const escapeText = value => String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
  const average = values => { const valid = values.filter(value => value != null && Number.isFinite(value)); return valid.length ? valid.reduce((sum, value) => sum + value, 0) / valid.length : null; };
  const median = values => { const valid = values.filter(value => value != null && Number.isFinite(value)).sort((a, b) => a - b); if (!valid.length) return null; const middle = Math.floor(valid.length / 2); return valid.length % 2 ? valid[middle] : (valid[middle - 1] + valid[middle]) / 2; };
  const directionFromReturn = value => value > 1.5 ? 'up' : value < -1.5 ? 'down' : 'neutral';
  const directionFromForecast = value => value.up >= value.down + 12 ? 'up' : value.down >= value.up + 12 ? 'down' : 'neutral';
  const directionLabel = value => value === 'up' ? '偏多' : value === 'down' ? '偏空' : '震盪';

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
    if (Math.abs(stock.change || 0) >= 7) events.push({ icon: '!', title: '單日波動較大', detail: `盤後漲跌幅 ${pct(stock.change)}，短線預測不確定性提高。`, level: 'warn' });
    if (indicators?.volumeRatio >= 1.5) events.push({ icon: '◫', title: '成交量明顯放大', detail: `近 5 日量能約為 20 日平均的 ${fmt(indicators.volumeRatio, 2)} 倍。`, level: 'warn' });
    if (indicators?.rsi14 >= 75) events.push({ icon: '▲', title: 'RSI 進入過熱區', detail: `RSI 14 為 ${fmt(indicators.rsi14)}，短線追價風險較高。`, level: 'warn' });
    if (indicators?.rsi14 <= 30) events.push({ icon: '▼', title: 'RSI 進入超賣區', detail: `RSI 14 為 ${fmt(indicators.rsi14)}，仍需觀察是否止跌。`, level: 'warn' });
    if (stock.rev != null && stock.rev < 0) events.push({ icon: '↘', title: '月營收年增為負', detail: `最新月營收年增 ${pct(stock.rev)}，成長動能需持續追蹤。`, level: 'bad' });
    if (stock.debt != null && stock.debt >= 70) events.push({ icon: '!', title: '負債比偏高', detail: `負債比 ${fmt(stock.debt)}%，財務彈性風險較高。`, level: 'bad' });
    if (stock.foreign != null && stock.foreign < 0) events.push({ icon: '◁', title: '外資當日賣超', detail: `外資買賣超 ${fmt(stock.foreign, 0)} 張。`, level: 'warn' });
    if (events.length === 1) events.push({ icon: '✓', title: '目前未偵測重大量價警示', detail: '仍應留意公司公告、產業消息及整體市場變化。', level: 'info' });
    return events;
  }
  function scenarioAnalysis(stock, forecast, indicators) {
    const volatility = forecast.expectedMove5 || 5;
    const support = indicators?.support || stock.close * (1 - volatility / 100);
    const resistance = indicators?.resistance || stock.close * (1 + volatility / 100);
    const optimism = Math.max(10, forecast.up);
    const pessimism = Math.max(10, forecast.down);
    const neutralProbability = Math.max(10, 100 - optimism - pessimism);
    return [
      { type: 'positive', title: '樂觀情境', probability: optimism, low: Math.max(stock.close, resistance * .99), high: stock.close * (1 + volatility * 1.35 / 100), trigger: '突破壓力且成交量同步增加' },
      { type: 'neutral', title: '中性情境', probability: neutralProbability, low: stock.close * (1 - volatility * .55 / 100), high: stock.close * (1 + volatility * .55 / 100), trigger: '量能持平，價格維持區間整理' },
      { type: 'negative', title: '悲觀情境', probability: pessimism, low: stock.close * (1 - volatility * 1.35 / 100), high: Math.min(stock.close, support * 1.01), trigger: '跌破支撐或法人籌碼持續轉弱' }
    ];
  }

  function recordPrediction(stock, forecast) {
    const logs = getPredictionLogs();
    const date = S.date || new Date().toISOString().slice(0, 10);
    const exists = logs.some(log => log.symbol === stock.symbol && log.prediction_date === date && log.model_version === PATCH_VERSION);
    if (exists) return;
    logs.unshift({
      local_id: createId(), symbol: stock.symbol, stock_name: stock.name, prediction_date: date,
      horizon_days: 5, reference_price: stock.close, predicted_direction: directionFromForecast(forecast),
      up_probability: forecast.up, neutral_probability: forecast.neutral, down_probability: forecast.down,
      confidence: forecast.confidence, expected_low: forecast.expectedLow, expected_high: forecast.expectedHigh,
      model_version: PATCH_VERSION, factors: { composite: forecast.composite, technical: forecast.technical, fundamental: forecast.fundamental, chip: forecast.chip, valuation: forecast.valuation },
      evaluated_at: null, actual_price: null, actual_return_pct: null, actual_direction: null, is_correct: null,
      created_at: new Date().toISOString()
    });
    setPredictionLogs(logs.slice(0, 500));
  }

  function evaluatePredictions(symbol, history) {
    const logs = getPredictionLogs();
    let changed = false;
    for (const log of logs) {
      if (log.symbol !== symbol || log.evaluated_at) continue;
      const index = history.findIndex(row => row.date >= log.prediction_date);
      if (index < 0 || history.length <= index + 5) continue;
      const actual = history[index + 5];
      const returnPct = (actual.close / log.reference_price - 1) * 100;
      const direction = directionFromReturn(returnPct);
      Object.assign(log, { evaluated_at: new Date().toISOString(), actual_price: actual.close, actual_return_pct: +returnPct.toFixed(2), actual_direction: direction, is_correct: direction === log.predicted_direction });
      changed = true;
    }
    if (changed) setPredictionLogs(logs);
  }

  function runTechnicalBacktest(stock, history) {
    const key = `${stock.symbol}-${history.at(-1)?.date || ''}`;
    if (patchState.backtestCache.has(key)) return patchState.backtestCache.get(key);
    const samples = [];
    for (let index = 80; index < history.length - 5; index += 5) {
      const past = history.slice(0, index + 1);
      const indicators = computeIndicators(past);
      if (!indicators) continue;
      const snapshot = { ...stock, close: past.at(-1).close, change: null, rev: null, revMom: null, revYtd: null, roe: null, eps: null, pe: null, pb: null, yield: null, debt: null, foreign: null, trust: null, dealer: null, marginChange: null };
      const forecast = calculateForecast(snapshot, indicators);
      const predicted = directionFromForecast(forecast);
      const returnPct = (history[index + 5].close / past.at(-1).close - 1) * 100;
      const actual = directionFromReturn(returnPct);
      samples.push({ date: past.at(-1).date, predicted, actual, returnPct: +returnPct.toFixed(2), correct: predicted === actual });
    }
    const result = {
      count: samples.length,
      hitRate: samples.length ? samples.filter(item => item.correct).length / samples.length * 100 : null,
      avgReturn: average(samples.map(item => item.returnPct)),
      avgWin: average(samples.filter(item => item.returnPct > 0).map(item => item.returnPct)),
      avgLoss: average(samples.filter(item => item.returnPct < 0).map(item => item.returnPct)),
      samples
    };
    patchState.backtestCache.set(key, result);
    return result;
  }

  function predictionStats() {
    const all = getPredictionLogs();
    const evaluated = all.filter(log => log.evaluated_at);
    const correct = evaluated.filter(log => log.is_correct);
    const last30 = evaluated.filter(log => Date.now() - new Date(log.prediction_date).getTime() <= 30 * 86400000);
    const last90 = evaluated.filter(log => Date.now() - new Date(log.prediction_date).getTime() <= 90 * 86400000);
    const accuracy = rows => rows.length ? rows.filter(row => row.is_correct).length / rows.length * 100 : null;
    return { all, evaluated, accuracy: accuracy(evaluated), accuracy30: accuracy(last30), accuracy90: accuracy(last90), correct: correct.length };
  }

  function scenarioHtml(stock, forecast, indicators) {
    return scenarioAnalysis(stock, forecast, indicators).map(item => `<div class="card patch-scenario ${item.type}"><div class="head"><div><b>${item.title}</b><div class="muted">觸發條件：${item.trigger}</div></div><b>${item.probability}%</b></div><div class="price">${fmt(item.low)}～${fmt(item.high)}</div><div class="muted">5 個交易日情境區間，非價格保證。</div></div>`).join('');
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
  function verifyPage() {
    const stats = predictionStats();
    const query = patchState.verifyQuery.trim().toLowerCase();
    const matches = query ? S.stocks.filter(stock => stock.symbol.includes(query) || stock.name.toLowerCase().includes(query)).slice(0, 10) : [];
    const rows = stats.all.filter(log => !query || log.symbol.includes(query) || String(log.stock_name || '').toLowerCase().includes(query));
    return `<h2>預測驗證</h2><p class="muted">系統會保存每次預測，五個交易日後比對實際收盤價。歷史回測只使用當時以前的價量資料。</p>
      <div class="grid">${metric('已保存預測', fmt(stats.all.length, 0))}${metric('已完成驗證', fmt(stats.evaluated.length, 0))}${metric('整體命中率', stats.accuracy == null ? '尚無樣本' : `${fmt(stats.accuracy, 1)}%`)}${metric('近 90 日命中率', stats.accuracy90 == null ? '尚無樣本' : `${fmt(stats.accuracy90, 1)}%`)}</div>
      <div class="card"><h3>查詢個股回測</h3><div class="search-row"><input id="patchVerifySearch" value="${escapeText(patchState.verifyQuery)}" placeholder="輸入代號或名稱"><button id="patchVerifyButton" class="btn">查詢</button></div>${matches.length ? `<div class="search-results">${matches.map(stock => `<button class="search-result" data-patch-backtest="${stock.symbol}"><span><b>${stock.name}</b><small class="muted"> ${stock.symbol}</small></span><span>執行回測</span></button>`).join('')}</div>` : ''}</div>
      <div class="card"><h3>預測紀錄</h3>${rows.length ? `<div class="table-wrap"><table><thead><tr><th>日期</th><th>股票</th><th>預測</th><th>機率</th><th>實際</th><th>結果</th></tr></thead><tbody>${rows.slice(0, 80).map(log => `<tr><td>${log.prediction_date}</td><td>${log.stock_name || log.symbol}</td><td>${directionLabel(log.predicted_direction)}</td><td>${fmt(log.up_probability, 0)}/${fmt(log.neutral_probability, 0)}/${fmt(log.down_probability, 0)}</td><td class="${cls(log.actual_return_pct)}">${log.actual_return_pct == null ? '待驗證' : pct(log.actual_return_pct)}</td><td>${log.is_correct == null ? '—' : log.is_correct ? '✓' : '×'}</td></tr>`).join('')}</tbody></table></div>` : '<div class="empty muted">開啟任何股票的趨勢預測後，就會開始累積紀錄。</div>'}</div>${disclaimer()}`;
  }

  function backtestHtml(result) {
    return `<div class="grid">${metric('回測樣本', fmt(result.count, 0))}${metric('方向命中率', result.hitRate == null ? '—' : `${fmt(result.hitRate, 1)}%`)}${metric('樣本平均報酬', pct(result.avgReturn))}${metric('平均獲利／虧損', `${pct(result.avgWin)} / ${pct(result.avgLoss)}`)}</div><div class="table-wrap" style="margin-top:10px"><table><thead><tr><th>日期</th><th>預測</th><th>5 日報酬</th><th>結果</th></tr></thead><tbody>${result.samples.slice(-15).reverse().map(item => `<tr><td>${item.date}</td><td>${directionLabel(item.predicted)}</td><td class="${cls(item.returnPct)}">${pct(item.returnPct)}</td><td>${item.correct ? '✓' : '×'}</td></tr>`).join('')}</tbody></table></div><div class="muted small" style="margin-top:8px">回測不套用目前的營收、財報或法人資料，避免偷看未來；因此結果和當下完整模型不完全相同。</div>`;
  }

  function journalStats() {
    const all = getJournal();
    const closed = all.filter(item => item.return_pct != null);
    const wins = closed.filter(item => item.return_pct > 0);
    const followed = all.filter(item => item.followed_plan != null);
    return {
      all, closed,
      winRate: closed.length ? wins.length / closed.length * 100 : null,
      averageReturn: average(closed.map(item => item.return_pct)),
      followRate: followed.length ? followed.filter(item => item.followed_plan).length / followed.length * 100 : null
    };
  }

  function watchSection() {
    const items = getWatchlist();
    const rows = items.map(item => ({ item, stock: S.stocks.find(stock => stock.symbol === item.symbol) })).filter(row => row.stock);
    if (!rows.length) return '<div class="card empty"><h3>尚未加入自選股票</h3><p class="muted">可在機會股或股票詳細頁加入。</p></div>';
    return `<div class="list two-col">${rows.map(({ item, stock }) => { const gain = item.addedPrice && stock.close ? (stock.close / item.addedPrice - 1) * 100 : null; const etf = instrumentGroup(stock) === 'etf'; return `<div class="card clickable" data-detail="${stock.symbol}"><div class="head"><div><b>${stock.name}</b><div class="muted">${stock.symbol} · ${stock.industry}</div></div><button class="icon-btn" data-watch="${stock.symbol}">移除</button></div><div class="grid">${metric('目前價格', fmt(stock.close))}${metric('加入後漲跌', `<span class="${cls(gain)}">${pct(gain)}</span>`)}${metric(etf ? '商品類型' : '月營收年增', etf ? 'ETF' : pct(stock.rev))}${metric(etf ? '成交量' : '機會分數', etf ? `${fmt(stock.volume, 0)} 張` : opportunityScore(stock))}</div><button class="btn" data-forecast="${stock.symbol}" style="width:100%;margin-top:10px">查看趨勢預測</button></div>`; }).join('')}</div>`;
  }

  function actionLabel(value) { return ({ observe: '觀察', buy: '買入紀錄', sell: '賣出紀錄', review: '事後檢討' })[value] || value; }
  function horizonLabel(value) { return ({ short: '短線 1–5 日', swing: '波段 1–4 週', medium: '中期 1–6 月', long: '長期 6 月以上' })[value] || '未設定期間'; }
  function journalSection() {
    const stats = journalStats();
    const header = `<div class="grid">${metric('紀錄筆數', fmt(stats.all.length, 0))}${metric('已完成交易', fmt(stats.closed.length, 0))}${metric('勝率', stats.winRate == null ? '尚無樣本' : `${fmt(stats.winRate, 1)}%`)}${metric('遵守計畫率', stats.followRate == null ? '尚無資料' : `${fmt(stats.followRate, 1)}%`)}</div><div class="row" style="margin-top:10px"><button id="patchNewJournal" class="btn grow">＋新增投資紀錄</button><button id="patchExportJournal" class="btn secondary">匯出</button></div>`;
    if (!stats.all.length) return `${header}<div class="card empty"><h3>尚未建立投資紀錄</h3><p class="muted">記錄當時理由、風險與結果，之後才能檢查自己是否遵守計畫。</p></div>`;
    return `${header}<div class="list">${stats.all.map(item => `<div class="card patch-journal"><div class="head"><div><b>${item.stock_name || item.symbol} ${item.symbol}</b><div class="muted">${item.entry_date} · ${actionLabel(item.action)} · ${horizonLabel(item.horizon)}</div></div>${item.return_pct != null ? `<b class="${cls(item.return_pct)}">${pct(item.return_pct)}</b>` : ''}</div>${item.thesis ? `<p>${escapeText(item.thesis)}</p>` : ''}<div class="rules">${item.risk_plan ? `<span>風險：${escapeText(item.risk_plan)}</span>` : ''}${item.target_plan ? `<span>目標：${escapeText(item.target_plan)}</span>` : ''}${item.followed_plan != null ? `<span>遵守計畫：${item.followed_plan ? '是' : '否'}</span>` : ''}</div><div class="row" style="margin-top:10px"><button class="btn secondary" data-patch-edit="${item.local_id}">編輯</button><button class="btn danger" data-patch-delete="${item.local_id}">刪除</button></div></div>`).join('')}</div>`;
  }

  function minePage() {
    return `<h2>我的</h2><div class="patch-tabs"><button data-patch-mine="watch" class="${patchState.mineTab === 'watch' ? 'active' : ''}">自選清單</button><button data-patch-mine="journal" class="${patchState.mineTab === 'journal' ? 'active' : ''}">投資紀錄</button></div>${patchState.mineTab === 'watch' ? watchSection() : journalSection()}${disclaimer()}`;
  }
  function openJournalModal(record = null, stock = null) {
    const item = record || { local_id: createId(), symbol: stock?.symbol || '', stock_name: stock?.name || '', entry_date: new Date().toISOString().slice(0, 10), action: 'observe', price: stock?.close ?? null, quantity: null, horizon: 'swing', thesis: '', risk_plan: '', target_plan: '', emotion: '', followed_plan: null, exit_price: null, exit_date: '', return_pct: null, result_note: '' };
    modalRoot.innerHTML = `<div class="modal"><div class="sheet"><button class="sheet-close">×</button><h2>${record ? '編輯' : '新增'}投資紀錄</h2><div class="grid"><label class="muted">股票代號<input id="journalSymbol" value="${escapeText(item.symbol)}"></label><label class="muted">股票名稱<input id="journalName" value="${escapeText(item.stock_name || '')}"></label><label class="muted">日期<input id="journalDate" type="date" value="${item.entry_date}"></label><label class="muted">類型<select id="journalAction"><option value="observe">觀察</option><option value="buy">買入紀錄</option><option value="sell">賣出紀錄</option><option value="review">事後檢討</option></select></label><label class="muted">價格<input id="journalPrice" type="number" step="0.01" value="${item.price ?? ''}"></label><label class="muted">數量／張數<input id="journalQuantity" type="number" step="0.001" value="${item.quantity ?? ''}"></label><label class="muted">預計期間<select id="journalHorizon"><option value="short">短線 1–5 日</option><option value="swing">波段 1–4 週</option><option value="medium">中期 1–6 月</option><option value="long">長期 6 月以上</option></select></label><label class="muted">當時情緒<input id="journalEmotion" value="${escapeText(item.emotion || '')}" placeholder="例如：冷靜、害怕錯過"></label></div><label class="muted">決策理由<textarea id="journalThesis">${escapeText(item.thesis || '')}</textarea></label><label class="muted">風險計畫<textarea id="journalRisk">${escapeText(item.risk_plan || '')}</textarea></label><label class="muted">目標計畫<textarea id="journalTarget">${escapeText(item.target_plan || '')}</textarea></label><div class="grid"><label class="muted">出場價格<input id="journalExitPrice" type="number" step="0.01" value="${item.exit_price ?? ''}"></label><label class="muted">出場日期<input id="journalExitDate" type="date" value="${item.exit_date || ''}"></label></div><label class="muted">事後檢討<textarea id="journalResult">${escapeText(item.result_note || '')}</textarea></label><label class="muted"><input id="journalFollowed" type="checkbox" style="width:auto" ${item.followed_plan ? 'checked' : ''}> 有遵守原本計畫</label><button id="journalSave" class="btn" style="width:100%;margin-top:12px">儲存紀錄</button></div></div>`;
    q('#journalAction').value = item.action || 'observe';
    q('#journalHorizon').value = item.horizon || 'swing';
    q('.sheet-close', modalRoot).onclick = closeModal;
    q('#journalSave').onclick = () => {
      const price = Number(q('#journalPrice').value) || null;
      const exitPrice = Number(q('#journalExitPrice').value) || null;
      const saved = {
        ...item,
        symbol: q('#journalSymbol').value.trim(), stock_name: q('#journalName').value.trim(), entry_date: q('#journalDate').value,
        action: q('#journalAction').value, price, quantity: Number(q('#journalQuantity').value) || null, horizon: q('#journalHorizon').value,
        emotion: q('#journalEmotion').value.trim(), thesis: q('#journalThesis').value.trim(), risk_plan: q('#journalRisk').value.trim(), target_plan: q('#journalTarget').value.trim(),
        exit_price: exitPrice, exit_date: q('#journalExitDate').value || '', result_note: q('#journalResult').value.trim(), followed_plan: q('#journalFollowed').checked,
        return_pct: price && exitPrice ? +((exitPrice / price - 1) * 100).toFixed(2) : null, updated_at: new Date().toISOString()
      };
      if (!saved.symbol) { alert('請輸入股票代號'); return; }
      const list = getJournal();
      const index = list.findIndex(row => row.local_id === saved.local_id);
      if (index >= 0) list[index] = saved; else list.unshift(saved);
      setJournal(list); closeModal(); patchState.mineTab = 'journal'; S.tab = 'mine'; render();
    };
  }

  function bindPatch() {
    q('#patchVerifySearch')?.addEventListener('input', event => { patchState.verifyQuery = event.target.value; });
    q('#patchVerifyButton')?.addEventListener('click', () => { patchState.verifyQuery = q('#patchVerifySearch')?.value || ''; render(); });
    qa('[data-patch-backtest]').forEach(button => button.onclick = async () => {
      const symbol = button.dataset.patchBacktest;
      const stock = S.stocks.find(item => item.symbol === symbol);
      modalRoot.innerHTML = '<div class="modal"><div class="sheet"><button class="sheet-close">×</button><h2>歷史回測</h2><div class="loading"><span class="spinner"></span>正在讀取歷史資料並回測…</div></div></div>';
      q('.sheet-close', modalRoot).onclick = closeModal;
      try {
        const history = await getHistory(symbol);
        evaluatePredictions(symbol, history.rows);
        const result = runTechnicalBacktest(stock, history.rows);
        modalRoot.innerHTML = `<div class="modal"><div class="sheet"><button class="sheet-close">×</button><h2>${stock.name} ${symbol} 回測</h2>${backtestHtml(result)}<div class="notice"><b>回測限制</b><br>歷史表現不代表未來結果，樣本數過少時不應視為可靠依據。</div></div></div>`;
        q('.sheet-close', modalRoot).onclick = closeModal;
      } catch (error) {
        modalRoot.innerHTML = `<div class="modal"><div class="sheet"><button class="sheet-close">×</button><h2>回測失敗</h2><div class="notice">${escapeText(error.message)}</div></div></div>`;
        q('.sheet-close', modalRoot).onclick = closeModal;
      }
    });
    qa('[data-patch-mine]').forEach(button => button.onclick = () => { patchState.mineTab = button.dataset.patchMine; render(); });
    q('#patchNewJournal')?.addEventListener('click', () => openJournalModal());
    q('#patchExportJournal')?.addEventListener('click', () => {
      const blob = new Blob([JSON.stringify(getJournal(), null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob); const anchor = document.createElement('a'); anchor.href = url; anchor.download = `台股智選-投資紀錄-${new Date().toISOString().slice(0, 10)}.json`; anchor.click(); URL.revokeObjectURL(url);
    });
    qa('[data-patch-edit]').forEach(button => button.onclick = () => openJournalModal(getJournal().find(item => item.local_id === button.dataset.patchEdit)));
    qa('[data-patch-delete]').forEach(button => button.onclick = () => { if (!confirm('確定刪除這筆紀錄？')) return; setJournal(getJournal().filter(item => item.local_id !== button.dataset.patchDelete)); render(); });
    qa('[data-patch-journal-stock]').forEach(button => button.onclick = () => openJournalModal(null, S.stocks.find(stock => stock.symbol === button.dataset.patchJournalStock)));
    qa('[data-patch-verify-stock]').forEach(button => button.onclick = () => { closeModal(); patchState.verifyQuery = button.dataset.patchVerifyStock; S.tab = 'verify'; render(); });
  }

  const originalOpenDetail = openDetail;
  openDetail = async function patchedOpenDetail(symbol, loadHistory = true) {
    await originalOpenDetail(symbol, loadHistory);
    const stock = S.stocks.find(item => item.symbol === symbol);
    if (!stock) return;
    try {
      const history = await getHistory(symbol);
      const forecast = calculateForecast(stock, history.indicators);
      recordPrediction(stock, forecast);
      evaluatePredictions(symbol, history.rows);
    } catch {
      recordPrediction(stock, calculateForecast(stock, null));
    }
  };

  const originalBind = bind;
  bind = function patchedBind() { originalBind(); bindPatch(); };
  const originalRender = render;
  render = function patchedRender() {
    qa('.bottom-nav button').forEach(button => button.classList.toggle('active', button.dataset.tab === S.tab));
    if (S.tab === 'verify') { app.innerHTML = verifyPage(); bind(); return; }
    if (S.tab === 'mine') { app.innerHTML = minePage(); bind(); return; }
    originalRender();
  };

  function updateNavigation() {
    const nav = q('.bottom-nav');
    if (!nav) return;
    const watchButton = q('[data-tab="watch"]', nav);
    if (watchButton) { watchButton.dataset.tab = 'mine'; watchButton.innerHTML = '<span>◎</span>我的'; }
    if (!q('[data-tab="verify"]', nav)) {
      const verifyButton = document.createElement('button');
      verifyButton.type = 'button'; verifyButton.dataset.tab = 'verify'; verifyButton.innerHTML = '<span>✓</span>預測驗證';
      nav.insertBefore(verifyButton, watchButton);
    }
  }

  updateNavigation();
  render();
})();
