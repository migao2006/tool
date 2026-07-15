'use strict';

const EDGE='/api/market-data';
const SUPABASE_URL='https://lfkdkdyaatdlizryiyon.supabase.co';
const SUPABASE_KEY='sb_publishable_r3h9eQIYdIqScvmc77avAg_OLgBT6lh';
const MODEL_VERSION='v16.3-persistent-backend';
const DISCLAIMER='未來漲跌預測是依公開資料、技術指標與固定權重計算的機率估計，僅供研究參考，不構成投資建議、買賣邀約或獲利保證。模型可能因突發消息、流動性、資料延遲及市場情緒而失準，投資人應自行判斷並承擔風險。';

const S={
  tab:'home',stocks:[],mode:'loading',date:'',fundStatus:'loading',fundPeriod:'',loading:true,
  historyCache:new Map(),historySignals:new Map(),backtestCache:new Map(),deepCache:new Map(),detailSymbol:null,forecastQuery:'',verifyQuery:'',verifySymbol:'',
  mineSub:'watch',session:null,isAdmin:false,adminState:'idle',adminLog:null,adminError:'',dataStatus:{},sourceDates:{},fundDates:{},syncState:'本機模式'
};

const app=document.querySelector('#app');
const modalRoot=document.querySelector('#modalRoot');
const q=(s,r=document)=>r.querySelector(s);
const qa=(s,r=document)=>[...r.querySelectorAll(s)];
let modalReturnFocus=null;
let modalFocusPrimed=false;

function modalFocusable(sheet){
  return qa('button:not([disabled]),a[href],input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])',sheet)
    .filter(element=>element.offsetParent!==null);
}
function enhanceModal(){
  const sheet=q('.sheet',modalRoot);if(!sheet)return;
  const shouldFocus=!modalFocusPrimed;
  if(shouldFocus&&document.activeElement instanceof HTMLElement)modalReturnFocus=document.activeElement;
  const heading=q('h2',sheet),close=q('.sheet-close',sheet);
  sheet.setAttribute('role','dialog');sheet.setAttribute('aria-modal','true');sheet.setAttribute('tabindex','-1');
  if(heading){heading.id=heading.id||'activeModalTitle';sheet.setAttribute('aria-labelledby',heading.id)}
  if(close){close.type='button';close.setAttribute('aria-label','關閉視窗');close.title='關閉視窗'}
  document.body.classList.add('modal-open');
  if(shouldFocus){modalFocusPrimed=true;requestAnimationFrame(()=>close?.focus({preventScroll:true}))}
}
new MutationObserver(enhanceModal).observe(modalRoot,{childList:true});
modalRoot.addEventListener('click',event=>{if(event.target===q('.modal',modalRoot)||event.target.closest('.sheet-close'))closeModal()});
document.addEventListener('keydown',event=>{
  const sheet=q('.sheet',modalRoot);if(!sheet)return;
  if(event.key==='Escape'){event.preventDefault();closeModal();return}
  if(event.key!=='Tab')return;
  const focusable=modalFocusable(sheet);if(!focusable.length){event.preventDefault();sheet.focus();return}
  const first=focusable[0],last=focusable.at(-1);
  if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus()}
  else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus()}
});
const clamp=(v,min,max)=>Math.max(min,Math.min(max,v));
const safe=v=>v==null||Number.isNaN(Number(v))?null:Number(v);
const fmt=(v,d=2)=>v==null||Number.isNaN(Number(v))?'—':Number(v).toLocaleString('zh-TW',{maximumFractionDigits:d});
const pct=(v,d=2)=>v==null||Number.isNaN(Number(v))?'—':`${v>0?'+':''}${fmt(v,d)}%`;
const cls=v=>v>0?'up':v<0?'down':'neutral';
const today=()=>new Date().toISOString().slice(0,10);
const uid=()=>crypto.randomUUID?crypto.randomUUID():`${Date.now()}-${Math.random().toString(16).slice(2)}`;
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const reasonDash=reason=>`—（${reason}）`;

function readLocal(key,fallback=[]){try{return JSON.parse(localStorage.getItem(key)||JSON.stringify(fallback))}catch{return fallback}}
function writeLocal(key,value){localStorage.setItem(key,JSON.stringify(value))}
function getWatchlist(){return readLocal('twss-watchlist-v15',[])}
function setWatchlist(v){writeLocal('twss-watchlist-v15',v)}
function getPredictions(){return readLocal('twss-predictions-v15',[])}
function setPredictions(v){writeLocal('twss-predictions-v15',v)}
function getJournal(){return readLocal('twss-journal-v15',[])}
function setJournal(v){writeLocal('twss-journal-v15',v)}
function isWatched(symbol){return getWatchlist().some(x=>x.symbol===symbol)}

const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function fetchJson(url,timeout=90000,retries=1){
  let lastError;
  for(let attempt=0;attempt<=retries;attempt++){
    const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),timeout);
    try{
      const r=await fetch(url,{cache:'default',signal:controller.signal,headers:{accept:'application/json'}});
      if(!r.ok){let body=null;try{body=await r.clone().json()}catch{}const error=new Error(body?.error||`HTTP ${r.status}`);error.status=r.status;error.code=body?.code||null;error.retryAfterAt=body?.retryAfterAt||null;throw error}
      return await r.json();
    }catch(error){
      lastError=error;const retryable=error.name==='AbortError'||error.status===429||error.status>=500;
      if(!retryable||attempt===retries)throw error;
      await wait(1400*(attempt+1));
    }finally{clearTimeout(timer)}
  }
  throw lastError;
}

function normalizeStock(item){return{
  symbol:'',name:'',industry:'未分類',market:'上市',instrumentType:'股票',close:null,change:null,open:null,high:null,low:null,
  volume:null,value:null,transactions:null,pe:null,pb:null,yield:null,revenue:null,revenuePreviousMonth:null,revenueLastYearMonth:null,revenueYtd:null,revenueLastYearYtd:null,rev:null,revMom:null,revYtd:null,revAcceleration:null,revPeriod:null,
  eps:null,roe:null,roeEstimated:false,roePeriod:null,grossMargin:null,operatingMargin:null,netMargin:null,debt:null,equityRatio:null,
  foreign:null,trust:null,dealer:null,inst:null,marginBalance:null,marginChange:null,shortBalance:null,shortChange:null,disp:null,full:null,demo:false,
  ...item,symbol:String(item.symbol||'')
}}

async function loadStocks(){
  S.loading=true;render();
  try{
    const payload=await fetchJson(`${EDGE}?type=stocks`,120000);
    if(!Array.isArray(payload.stocks)||payload.stocks.length<20)throw new Error(payload.error||'盤後資料筆數不足');
    S.stocks=payload.stocks.map(normalizeStock);S.mode=payload.mode||'partial';S.date=payload.date||today();S.dataStatus=payload.sourceStatus||{};S.sourceDates=payload.dates||{};S.loading=false;
    q('#marketDate').textContent=`最新交易日 ${S.date} · 盤後資料（非即時）`;
    q('#dataMode').textContent=S.mode==='live'?'官方日期已核對':S.mode==='partial'?'部分官方資料':'資料不足';
    render();loadFundamentals();
  }catch(error){
    S.loading=false;app.innerHTML=`<div class="card error-card"><h3>股票資料載入失敗</h3><p class="muted">${esc(error.message)}</p><button id="retryLoad" class="btn">重新載入</button></div>`;q('#retryLoad').onclick=loadStocks;
  }
}

async function loadFundamentals(){
  S.fundStatus='loading';render();
  const merged=new Map();let revenueOk=false,financialOk=false;const periods=[];
  const applyPayload=(payload,type)=>{
    const rows=payload?.fundamentals||[];
    if(type==='revenue'&&rows.some(x=>x.rev!=null))revenueOk=true;
    if(type==='financials'&&rows.some(x=>x.roe!=null||x.eps!=null))financialOk=true;
    if(payload?.period)periods.push(payload.period);
    if(payload?.dates)S.fundDates[type]=payload.dates;
    rows.forEach(row=>merged.set(String(row.symbol),{...(merged.get(String(row.symbol))||{}),...row}));
    S.stocks=S.stocks.map(stock=>({...stock,...(merged.get(stock.symbol)||{})}));
    S.fundStatus=revenueOk||financialOk?'partial':'loading';render();
  };
  const [revenueResult,financialResult]=await Promise.allSettled([
    fetchJson(`${EDGE}?type=revenue`,90000),
    fetchJson(`${EDGE}?type=financials`,180000)
  ]);
  if(revenueResult.status==='fulfilled')applyPayload(revenueResult.value,'revenue');
  if(financialResult.status==='fulfilled')applyPayload(financialResult.value,'financials');
  S.fundStatus=revenueOk&&financialOk?'ready':revenueOk||financialOk?'partial':'error';
  S.fundPeriod=periods.sort().at(-1)||'';render();
  if(S.detailSymbol)openDetail(S.detailSymbol,false);
}

function normalizedHistory(payload){
  if(!Array.isArray(payload?.history)||payload.history.length<60)throw new Error(payload?.error||'可用交易日不足 60 日，暫不計算完整技術面');
  return payload.history.map(x=>({date:x.date,open:safe(x.open),high:safe(x.high),low:safe(x.low),close:safe(x.close),volume:safe(x.volume),value:safe(x.value),transactions:safe(x.transactions)})).filter(x=>x.close!=null&&x.high!=null&&x.low!=null)
}
async function getHistory(symbol){
  const cached=S.historyCache.get(symbol);if(cached)return cached instanceof Promise?cached:Promise.resolve(cached);
  const promise=(async()=>{const stock=S.stocks.find(x=>x.symbol===symbol)||{},params=new URLSearchParams({type:'history',symbol,months:'18',market:stock.market||'上市'});const payload=await fetchJson(`${EDGE}?${params}`,120000,0);
    const rows=normalizedHistory(payload),result={rows,indicators:computeIndicators(rows),source:payload.source||`${stock.market||'台股'}歷史行情`};S.historyCache.set(symbol,result);return result})();
  S.historyCache.set(symbol,promise);try{return await promise}catch(error){S.historyCache.delete(symbol);throw error}
}
async function getDeepAnalysis(symbol){
  const cached=S.deepCache.get(symbol);if(cached)return cached instanceof Promise?cached:Promise.resolve(cached);
  const promise=fetchJson(`${EDGE}?type=deep&symbol=${encodeURIComponent(symbol)}`,45000,0).then(payload=>{S.deepCache.set(symbol,payload);return payload});
  S.deepCache.set(symbol,promise);try{return await promise}catch(error){S.deepCache.delete(symbol);throw error}
}

/* Supabase auth and optional cloud sync */
const SESSION_KEY='twss-supabase-session-v15';
function sessionUserId(session=S.session){return session?.user?.id||decodeJwtSub(session?.access_token)||null}
function clearAdminState(){S.isAdmin=false;S.adminState='idle';S.adminLog=null;S.adminError='';if(S.tab==='admin')S.tab='home'}
function updateAccountUi(){const account=q('#accountBtn'),admin=q('#adminBtn');if(account)account.textContent=S.session?'帳戶':'登入';if(admin){admin.hidden=!S.isAdmin;admin.setAttribute('aria-hidden',String(!S.isAdmin));admin.classList.toggle('active',S.tab==='admin')}}
function storeSession(session){const previousId=sessionUserId(),nextId=sessionUserId(session);if(!session||previousId!==nextId)clearAdminState();S.session=session;if(session)localStorage.setItem(SESSION_KEY,JSON.stringify(session));else localStorage.removeItem(SESSION_KEY);updateAccountUi()}
async function sb(path,options={}){
  const headers={apikey:SUPABASE_KEY,'Content-Type':'application/json',...(options.headers||{})};
  if(options.auth!==false&&S.session?.access_token)headers.Authorization=`Bearer ${S.session.access_token}`;
  const r=await fetch(SUPABASE_URL+path,{method:options.method||'GET',headers,body:options.body===undefined?undefined:JSON.stringify(options.body),cache:'no-store'});
  let data=null;try{data=await r.json()}catch{}if(!r.ok){const error=new Error(data?.message||data?.error_description||data?.error||`HTTP ${r.status}`);error.status=r.status;error.code=data?.code||null;throw error}return data;
}
async function refreshSession(){
  if(!S.session)return false;if((S.session.expires_at||0)>Date.now()/1000+90)return true;
  if(!S.session.refresh_token){storeSession(null);return false}
  try{const s=await sb('/auth/v1/token?grant_type=refresh_token',{method:'POST',body:{refresh_token:S.session.refresh_token},auth:false});s.expires_at=Math.floor(Date.now()/1000)+(s.expires_in||3600);storeSession(s);return true}catch{storeSession(null);return false}
}
async function refreshAdminAccess(){
  if(!S.session||!await refreshSession()){clearAdminState();updateAccountUi();return false}
  try{S.isAdmin=(await sb('/rest/v1/rpc/twss_is_admin',{method:'POST',body:{}}))===true}catch{S.isAdmin=false}
  if(!S.isAdmin){S.adminState='idle';S.adminLog=null;S.adminError='';if(S.tab==='admin')S.tab='home'}
  updateAccountUi();return S.isAdmin
}
async function login(email,password){const s=await sb('/auth/v1/token?grant_type=password',{method:'POST',body:{email,password},auth:false});s.expires_at=Math.floor(Date.now()/1000)+(s.expires_in||3600);storeSession(s);await refreshAdminAccess();await cloudPull()}
async function signup(email,password){const s=await sb(`/auth/v1/signup?redirect_to=${encodeURIComponent(location.origin)}`,{method:'POST',body:{email,password},auth:false});if(s?.access_token){s.expires_at=Math.floor(Date.now()/1000)+(s.expires_in||3600);storeSession(s);await refreshAdminAccess();await cloudPull();return true}return false}
async function cloudPull(){
  if(!await refreshSession())return;S.syncState='同步中…';
  try{
    const [pred,journal]=await Promise.all([
      sb('/rest/v1/prediction_logs?select=*&order=prediction_date.desc'),
      sb('/rest/v1/investment_journal?select=*&order=entry_date.desc')
    ]);
    if(pred?.length)setPredictions(pred.map(x=>({...x,local_id:x.id})));
    if(journal?.length)setJournal(journal.map(x=>({...x,local_id:x.id})));
    S.syncState='雲端已同步';render();
  }catch(e){S.syncState=`同步失敗：${e.message}`}
}
async function upsertPredictionCloud(record){if(!await refreshSession())return;const body={user_id:S.session.user?.id||decodeJwtSub(S.session.access_token),symbol:record.symbol,stock_name:record.stock_name,prediction_date:record.prediction_date,horizon_days:record.horizon_days,reference_price:record.reference_price,predicted_direction:record.predicted_direction,up_probability:record.up_probability,neutral_probability:record.neutral_probability,down_probability:record.down_probability,confidence:record.confidence,expected_low:record.expected_low,expected_high:record.expected_high,model_version:record.model_version,factors:record.factors,evaluated_at:record.evaluated_at||null,actual_price:record.actual_price??null,actual_return_pct:record.actual_return_pct??null,actual_direction:record.actual_direction||null,is_correct:record.is_correct??null};await sb('/rest/v1/prediction_logs?on_conflict=user_id,symbol,prediction_date,horizon_days,model_version',{method:'POST',headers:{Prefer:'resolution=merge-duplicates,return=minimal'},body})}
async function upsertJournalCloud(record){if(!await refreshSession())return;const userId=S.session.user?.id||decodeJwtSub(S.session.access_token);const body={user_id:userId,symbol:record.symbol,stock_name:record.stock_name,entry_date:record.entry_date,action:record.action,price:record.price??null,quantity:record.quantity??null,horizon:record.horizon||null,thesis:record.thesis||null,risk_plan:record.risk_plan||null,target_plan:record.target_plan||null,emotion:record.emotion||null,followed_plan:record.followed_plan??null,exit_price:record.exit_price??null,exit_date:record.exit_date||null,return_pct:record.return_pct??null,result_note:record.result_note||null,tags:record.tags||[]};if(record.id&&String(record.id).includes('-'))await sb(`/rest/v1/investment_journal?id=eq.${record.id}`,{method:'PATCH',headers:{Prefer:'return=minimal'},body});else await sb('/rest/v1/investment_journal',{method:'POST',headers:{Prefer:'return=minimal'},body})}
function decodeJwtSub(token){try{return JSON.parse(atob(token.split('.')[1].replace(/-/g,'+').replace(/_/g,'/'))).sub}catch{return null}}
async function logoutAccount(){try{if(S.session?.access_token)await sb('/auth/v1/logout',{method:'POST'})}catch{}finally{storeSession(null);S.syncState='本機模式';closeModal();render()}}
async function initSession(){let saved=null;try{saved=JSON.parse(localStorage.getItem(SESSION_KEY)||'null')}catch{}storeSession(saved);if(S.session&&await refreshSession()){try{S.session.user=await sb('/auth/v1/user');storeSession(S.session)}catch{}await refreshAdminAccess();cloudPull()}else{clearAdminState();updateAccountUi()}}

function mean(values){const v=values.filter(x=>x!=null&&Number.isFinite(x));return v.length?v.reduce((a,b)=>a+b,0)/v.length:null}
function sma(values,period){return values.length>=period?mean(values.slice(-period)):null}
function emaSeries(values,period){if(!values.length)return[];const m=2/(period+1),out=[values[0]];for(let i=1;i<values.length;i++)out.push(values[i]*m+out[i-1]*(1-m));return out}
function std(values){const m=mean(values);return m==null?null:Math.sqrt(mean(values.map(v=>(v-m)**2)))}
function calcRsi(values,period=14){if(values.length<=period)return null;const changes=values.slice(1).map((v,i)=>v-values[i]);let gains=0,losses=0;for(const c of changes.slice(0,period)){if(c>0)gains+=c;else losses-=c}let avgGain=gains/period,avgLoss=losses/period;for(const c of changes.slice(period)){avgGain=(avgGain*(period-1)+Math.max(c,0))/period;avgLoss=(avgLoss*(period-1)+Math.max(-c,0))/period}if(avgLoss===0)return 100;return 100-100/(1+avgGain/avgLoss)}
function calcAtr(rows,period=14){if(rows.length<=period)return null;const tr=rows.slice(1).map((r,i)=>Math.max(r.high-r.low,Math.abs(r.high-rows[i].close),Math.abs(r.low-rows[i].close)));return mean(tr.slice(-period))}
function computeIndicators(rows){
  const closes=rows.map(r=>r.close).filter(v=>v!=null),volumes=rows.map(r=>r.volume).filter(v=>v!=null);if(closes.length<20)return null;
  const ma5=sma(closes,5),ma20=sma(closes,20),ma60=sma(closes,60),ema12=emaSeries(closes,12),ema26=emaSeries(closes,26);
  const macdSeries=closes.map((_,i)=>(ema12[i]??0)-(ema26[i]??0)),signalSeries=emaSeries(macdSeries,9);
  const macd=macdSeries.at(-1),signal=signalSeries.at(-1),histogram=macd-signal,rsi14=calcRsi(closes,14),atr14=calcAtr(rows,14),last=closes.at(-1);
  const w20=closes.slice(-20),mid=mean(w20),dev=std(w20),upper=mid==null||dev==null?null:mid+2*dev,lower=mid==null||dev==null?null:mid-2*dev;
  const momentum5=closes.length>5?(last/closes.at(-6)-1)*100:null,momentum20=closes.length>20?(last/closes.at(-21)-1)*100:null;
  const volume5=sma(volumes,5),volume20=sma(volumes,20),volumeRatio=volume5!=null&&volume20?volume5/volume20:null;
  const recent=rows.slice(-20),support=recent.length?Math.min(...recent.map(r=>r.low)):null,resistance=recent.length?Math.max(...recent.map(r=>r.high)):null;
  return{ma5,ma20,ma60,rsi14,atr14,atrPct:atr14&&last?atr14/last*100:null,macd,signal,histogram,bollingerUpper:upper,bollingerMiddle:mid,bollingerLower:lower,momentum5,momentum20,volume5,volume20,volumeRatio,support,resistance,last,rows:rows.length}
}

function calculateForecast(stock,indicators){
  const isEtf=stock.instrumentType==='ETF'||/^00\d{2,4}[A-Z]?$/i.test(stock.symbol);
  let technical=0,fundamental=0,chip=0,valuation=0,riskPenalty=0;const positive=[],negative=[],missing=[];
  if(indicators){
    if(stock.close>indicators.ma5){technical+=7;positive.push('股價站上 5 日均線')}else technical-=5;
    if(indicators.ma5!=null&&indicators.ma20!=null&&indicators.ma5>indicators.ma20){technical+=10;positive.push('短期均線偏多')}else technical-=7;
    if(indicators.ma20!=null&&indicators.ma60!=null){if(indicators.ma20>indicators.ma60){technical+=13;positive.push('20 日均線高於 60 日均線')}else{technical-=11;negative.push('中期均線偏弱')}}else missing.push('60 日均線');
    if(indicators.histogram!=null){if(indicators.histogram>0){technical+=10;positive.push('MACD 柱狀體為正')}else{technical-=10;negative.push('MACD 柱狀體為負')}}
    if(indicators.rsi14!=null){if(indicators.rsi14>=50&&indicators.rsi14<=68)technical+=8;else if(indicators.rsi14>75){technical-=9;riskPenalty+=7;negative.push('RSI 過熱')}else if(indicators.rsi14<35){technical-=4;riskPenalty+=4;negative.push('RSI 偏弱')}}
    if(indicators.momentum5!=null)technical+=clamp(indicators.momentum5*1.2,-10,10);
    if(indicators.momentum20!=null)technical+=clamp(indicators.momentum20*.6,-12,12);
    if(indicators.volumeRatio!=null){if(indicators.volumeRatio>1.15&&(stock.change||0)>0){technical+=6;positive.push('量價同步')}if(indicators.volumeRatio>1.5&&(stock.change||0)<0){technical-=7;negative.push('下跌放量')}}
    if(indicators.atrPct!=null&&indicators.atrPct>5){riskPenalty+=9;negative.push('短線波動較大')}
  }else missing.push('歷史價格與技術指標');
  if(!isEtf){
    if(stock.rev!=null){if(stock.rev>=30){fundamental+=20;positive.push('月營收年增強勁')}else if(stock.rev>=10)fundamental+=13;else if(stock.rev>0)fundamental+=5;else{fundamental-=10;negative.push('月營收年增為負')}}else missing.push('月營收年增率');
    if(stock.revMom!=null)fundamental+=clamp(stock.revMom*.25,-7,7);
    if(stock.revYtd!=null)fundamental+=clamp(stock.revYtd*.18,-6,8);
    if(stock.roe!=null){if(stock.roe>=15){fundamental+=14;positive.push('ROE 表現佳')}else if(stock.roe>=8)fundamental+=8;else if(stock.roe<0)fundamental-=10}else missing.push('ROE');
    if(stock.eps!=null)fundamental+=stock.eps>0?6:-8;else missing.push('EPS');
    if(stock.operatingMargin!=null)fundamental+=stock.operatingMargin>10?5:stock.operatingMargin<0?-7:1;
    if(stock.debt!=null){if(stock.debt>75){fundamental-=7;riskPenalty+=5;negative.push('負債比偏高')}else if(stock.debt<50)fundamental+=3}else missing.push('負債比');
    if(stock.pe!=null&&stock.pe>0){if(stock.pe<=15)valuation+=12;else if(stock.pe<=25)valuation+=7;else if(stock.pe<=35)valuation+=2;else{valuation-=7;negative.push('本益比偏高')}}else missing.push('本益比');
    if(stock.pb!=null)valuation+=stock.pb<=2?5:stock.pb<=3?2:stock.pb>6?-4:0;
    if(stock.yield!=null&&stock.yield>=3)valuation+=3;
  }else{
    if(stock.yield!=null){valuation+=stock.yield>=5?8:stock.yield>=3?5:2;positive.push(`ETF 殖利率 ${fmt(stock.yield)}%`)}
    if((stock.volume||0)>=5000){fundamental+=8;positive.push('ETF 成交量充足')}else if((stock.volume||0)<500){riskPenalty+=8;negative.push('ETF 流動性偏低')}
  }
  if(stock.foreign!=null){if(stock.foreign>0){chip+=10;positive.push('外資買超')}else if(stock.foreign<0)chip-=8}else missing.push('外資買賣超');
  if(stock.trust!=null)chip+=stock.trust>0?7:stock.trust<0?-5:0;if(stock.dealer!=null)chip+=stock.dealer>0?3:stock.dealer<0?-2:0;
  if(stock.marginChange!=null&&stock.marginChange>0&&(stock.change||0)<0){chip-=4;riskPenalty+=3;negative.push('下跌且融資增加')}
  const tn=clamp(technical,-55,55),fn=clamp(fundamental,-35,35),cn=clamp(chip,-20,20),vn=clamp(valuation,-15,15);
  const composite=isEtf?tn*.68+fn*.10+cn*.16+vn*.06-riskPenalty*.4:tn*.52+fn*.26+cn*.15+vn*.07-riskPenalty*.35;
  const neutralProbability=clamp(29-Math.abs(composite)*.25+(indicators?.atrPct>5?5:0),12,38),directional=100-neutralProbability,upShare=1/(1+Math.exp(-composite/11));
  let up=Math.round(directional*upShare),down=Math.round(directional-directional*upShare),neutral=100-up-down;
  const required=isEtf?[stock.volume,stock.value,stock.yield,stock.foreign,stock.inst,indicators?.ma20,indicators?.ma60,indicators?.rsi14,indicators?.macd,indicators?.atrPct]:[stock.rev,stock.revMom,stock.roe,stock.eps,stock.pe,stock.pb,stock.debt,stock.foreign,indicators?.ma20,indicators?.rsi14,indicators?.macd,indicators?.atrPct];
  const available=required.filter(v=>v!=null).length;
  const completeness=Math.round(available/required.length*100),confidence=clamp(Math.round(completeness*.78+Math.min(Math.abs(composite),30)*.55-riskPenalty),25,90);
  const shortLabel=up>=down+12?'短期偏多':down>=up+12?'短期偏空':'短期震盪';
  const mediumScore=(indicators?.ma20&&indicators?.ma60?(indicators.ma20>indicators.ma60?18:-18):0)+(isEtf?fn*.15+vn*.15+cn*.45:fn*.55+vn*.2+cn*.25);
  const mediumLabel=mediumScore>=10?'中期偏多':mediumScore<=-10?'中期偏空':'中期盤整';
  const atrPct=indicators?.atrPct??Math.max(2,Math.abs(stock.change||0)*.8),expectedMove5=clamp(atrPct*Math.sqrt(5)*.75,2,18);
  return{up,down,neutral,confidence,completeness,shortLabel,mediumLabel,composite:+composite.toFixed(1),technical:+tn.toFixed(1),fundamental:+fn.toFixed(1),chip:+cn.toFixed(1),valuation:+vn.toFixed(1),riskPenalty,expectedMove5,expectedLow:stock.close*(1-expectedMove5/100),expectedHigh:stock.close*(1+expectedMove5/100),positive:[...new Set(positive)].slice(0,8),negative:[...new Set(negative)].slice(0,8),missing:[...new Set(missing)].slice(0,8)}
}

function opportunityScore(stock){let score=0;if(stock.rev!=null)score+=stock.rev>=30?28:stock.rev>=20?24:stock.rev>=10?20:stock.rev>0?10:0;if(stock.revMom!=null)score+=stock.revMom>=10?10:stock.revMom>0?6:0;if(stock.revYtd!=null)score+=stock.revYtd>=10?7:stock.revYtd>0?3:0;if(stock.roe!=null)score+=stock.roe>=15?15:stock.roe>=10?12:stock.roe>=8?8:0;if(stock.eps!=null&&stock.eps>0)score+=5;if(stock.pe!=null&&stock.pe>0)score+=stock.pe<=15?10:stock.pe<=25?7:stock.pe<=35?3:0;if(stock.pb!=null)score+=stock.pb<=2?4:stock.pb<=3?2:0;if(stock.foreign>0)score+=6;if(stock.trust>0)score+=4;if((stock.volume||0)>=1000)score+=6;else if((stock.volume||0)>=500)score+=3;if(stock.debt!=null&&stock.debt<=55)score+=3;return Math.min(100,Math.round(score))}
function instrumentGroup(stock){if(stock.instrumentType==='ETF'||/^00\d{2,4}[A-Z]?$/i.test(stock.symbol))return'etf';return stock.market==='上櫃'?'otc':'listed'}
function opportunityEligible(stock){const group=instrumentGroup(stock),floor=group==='otc'?100:300;return group!=='etf'&&stock.rev!=null&&stock.rev>=10&&(stock.volume||0)>=floor&&(stock.pe==null||(stock.pe>0&&stock.pe<=35))&&(stock.roe==null||stock.roe>=8)&&stock.disp!==true&&stock.full!==true}

function marketEnvironment(){
  const tradable=S.stocks.filter(x=>x.change!=null),up=tradable.filter(x=>x.change>0).length,down=tradable.filter(x=>x.change<0).length,flat=tradable.length-up-down;
  const avgChange=mean(tradable.map(x=>x.change))||0,totalVolume=S.stocks.reduce((a,x)=>a+(x.volume||0),0),foreign=S.stocks.reduce((a,x)=>a+(x.foreign||0),0),inst=S.stocks.reduce((a,x)=>a+(x.inst||0),0);
  const breadth=tradable.length?up/tradable.length*100:0;
  const label=breadth>=60&&avgChange>0?'市場偏多':breadth<=40&&avgChange<0?'市場偏空':'市場震盪';
  const confidence=clamp(Math.round(Math.abs(breadth-50)*1.3+Math.abs(avgChange)*8),30,85);
  const industries=[...new Set(S.stocks.map(x=>x.industry).filter(Boolean))].map(industry=>{
    const rows=S.stocks.filter(x=>x.industry===industry),valid=rows.filter(x=>x.change!=null);return{industry,count:rows.length,avgChange:mean(valid.map(x=>x.change))||0,breadth:valid.length?valid.filter(x=>x.change>0).length/valid.length*100:0,rev:mean(rows.map(x=>x.rev)),foreign:rows.reduce((a,x)=>a+(x.foreign||0),0)}
  }).filter(x=>x.count>=3).sort((a,b)=>(b.avgChange+b.breadth/100)-(a.avgChange+a.breadth/100));
  return{up,down,flat,avgChange,totalVolume,foreign,inst,breadth,label,confidence,industries}
}

function percentile(values,value,higherIsBetter=true){const v=values.filter(x=>x!=null&&Number.isFinite(x));if(!v.length||value==null)return null;const rank=v.filter(x=>higherIsBetter?x<=value:x>=value).length;return Math.round(rank/v.length*100)}
function peerComparison(stock){
  const group=instrumentGroup(stock);let peers=S.stocks.filter(x=>instrumentGroup(x)===group&&x.industry===stock.industry&&x.symbol!==stock.symbol);if(peers.length<4)peers=S.stocks.filter(x=>instrumentGroup(x)===group&&x.symbol!==stock.symbol);
  const definitions=group==='etf'?
    [['殖利率','yield',true,'%'],['成交量','volume',true,' 張'],['成交金額','value',true,' 元'],['三大法人','inst',true,' 張'],['單日漲跌','change',true,'%']]:
    [['月營收年增','rev',true,'%'],['ROE','roe',true,'%'],['本益比','pe',false,''],['殖利率','yield',true,'%'],['外資買賣超','foreign',true,' 張'],['單日漲跌','change',true,'%']];
  const rows=definitions.map(([label,key,higher,suffix])=>({label,value:stock[key],median:median(peers.map(x=>x[key])),percentile:percentile(peers.map(x=>x[key]),stock[key],higher),suffix,higher}));
  return{peerCount:peers.length,rows}
}
function median(values){const v=values.filter(x=>x!=null&&Number.isFinite(x)).sort((a,b)=>a-b);if(!v.length)return null;const m=Math.floor(v.length/2);return v.length%2?v[m]:(v[m-1]+v[m])/2}

function nextRevenueWindow(){const now=new Date(),next=new Date(now.getFullYear(),now.getMonth()+1,1);return`${next.getFullYear()}-${String(next.getMonth()+1).padStart(2,'0')} 上旬`}
function buildEvents(stock,indicators){
  const events=instrumentGroup(stock)==='etf'?[{icon:'◷',title:'ETF 定期觀察',detail:'追蹤指數成分調整、折溢價、流動性與配息公告',level:'info'}]:[{icon:'◷',title:'下次月營收觀察窗口',detail:nextRevenueWindow(),level:'info'}];
  if(stock.rev!=null&&stock.rev<0)events.push({icon:'!',title:'營收年增轉負',detail:`最新月營收年增 ${pct(stock.rev)}`,level:'bad'});
  if(stock.revMom!=null&&stock.revMom<=-15)events.push({icon:'!',title:'單月營收明顯下滑',detail:`月增率 ${pct(stock.revMom)}`,level:'bad'});
  if(Math.abs(stock.change||0)>=5)events.push({icon:'↕',title:'單日價格波動較大',detail:`今日漲跌 ${pct(stock.change)}`,level:'warn'});
  if(indicators?.volumeRatio>=1.5)events.push({icon:'▥',title:'成交量明顯放大',detail:`5 日／20 日量能比 ${fmt(indicators.volumeRatio)} 倍`,level:'warn'});
  if(indicators?.rsi14>=70)events.push({icon:'▲',title:'RSI 進入偏熱區',detail:`RSI ${fmt(indicators.rsi14)}`,level:'warn'});
  if(indicators?.rsi14<=30)events.push({icon:'▼',title:'RSI 進入偏弱區',detail:`RSI ${fmt(indicators.rsi14)}`,level:'bad'});
  if(stock.foreign!=null&&stock.foreign<-1000)events.push({icon:'外',title:'外資當日賣超',detail:`${fmt(stock.foreign,0)} 張`,level:'bad'});
  if(stock.marginChange!=null&&stock.marginChange>0&&(stock.change||0)<0)events.push({icon:'融',title:'下跌伴隨融資增加',detail:`融資增減 ${fmt(stock.marginChange,0)} 張`,level:'warn'});
  if(indicators?.resistance&&stock.close>=indicators.resistance*.98)events.push({icon:'壓',title:'接近 20 日壓力',detail:`壓力約 ${fmt(indicators.resistance)} 元`,level:'warn'});
  if(indicators?.support&&stock.close<=indicators.support*1.02)events.push({icon:'撐',title:'接近 20 日支撐',detail:`支撐約 ${fmt(indicators.support)} 元`,level:'bad'});
  if(stock.disp===true)events.push({icon:'處',title:'處置股票',detail:'交易限制可能影響流動性',level:'bad'});
  if(stock.full===true)events.push({icon:'全',title:'全額交割股票',detail:'交易風險較高',level:'bad'});
  return events;
}

function scenarioAnalysis(stock,forecast,indicators){
  const atr=indicators?.atrPct??forecast.expectedMove5/Math.sqrt(5)/.75;
  const support=indicators?.support??stock.close*(1-forecast.expectedMove5/100),resistance=indicators?.resistance??stock.close*(1+forecast.expectedMove5/100);
  return[
    {type:'good',title:'樂觀情境',prob:forecast.up,range:[Math.max(stock.close,resistance*.99),stock.close*(1+clamp(forecast.expectedMove5*1.15,3,22)/100)],trigger:'突破壓力、量能維持，法人籌碼未轉弱'},
    {type:'base',title:'中性情境',prob:forecast.neutral,range:[stock.close*(1-clamp(atr*.7,1.5,8)/100),stock.close*(1+clamp(atr*.7,1.5,8)/100)],trigger:'量價與籌碼缺乏明確方向，維持區間震盪'},
    {type:'bad',title:'悲觀情境',prob:forecast.down,range:[stock.close*(1-clamp(forecast.expectedMove5*1.2,3,24)/100),Math.min(stock.close,support*1.01)],trigger:'跌破支撐、下跌放量或法人轉為持續賣超'}
  ]
}

function directionFromReturn(ret){return ret>1.5?'up':ret<-1.5?'down':'neutral'}
function directionFromForecast(f){return f.up>=f.down+12?'up':f.down>=f.up+12?'down':'neutral'}
function recordPrediction(stock,forecast){
  const list=getPredictions(),key=`${stock.symbol}-${today()}-5-${MODEL_VERSION}`;if(list.some(x=>x.key===key))return;
  const rec={key,local_id:uid(),symbol:stock.symbol,stock_name:stock.name,prediction_date:today(),horizon_days:5,reference_price:stock.close,predicted_direction:directionFromForecast(forecast),up_probability:forecast.up,neutral_probability:forecast.neutral,down_probability:forecast.down,confidence:forecast.confidence,expected_low:forecast.expectedLow,expected_high:forecast.expectedHigh,model_version:MODEL_VERSION,factors:{technical:forecast.technical,fundamental:forecast.fundamental,chip:forecast.chip,valuation:forecast.valuation,completeness:forecast.completeness},created_at:new Date().toISOString()};
  list.unshift(rec);setPredictions(list);upsertPredictionCloud(rec).catch(()=>{});
}
function evaluatePredictionsForSymbol(symbol,history){
  const list=getPredictions();let changed=false;
  list.forEach(rec=>{
    if(rec.symbol!==symbol||rec.evaluated_at)return;const startIndex=history.findIndex(r=>r.date>=rec.prediction_date);if(startIndex<0||history.length<=startIndex+5)return;const actual=history[startIndex+5],ret=(actual.close/rec.reference_price-1)*100,dir=directionFromReturn(ret);Object.assign(rec,{evaluated_at:new Date().toISOString(),actual_price:actual.close,actual_return_pct:+ret.toFixed(2),actual_direction:dir,is_correct:dir===rec.predicted_direction});changed=true;upsertPredictionCloud(rec).catch(()=>{})
  });if(changed)setPredictions(list)
}

function runTechnicalBacktest(stock,history){
  const key=`${stock.symbol}-${history.at(-1)?.date||''}`;if(S.backtestCache.has(key))return S.backtestCache.get(key);
  const samples=[];
  for(let i=60;i<history.length-5;i+=5){const slice=history.slice(0,i+1),ind=computeIndicators(slice);if(!ind)continue;const historicalStock={...stock,close:slice.at(-1).close,change:slice.length>1?(slice.at(-1).close/slice.at(-2).close-1)*100:0,rev:null,revMom:null,revYtd:null,roe:null,eps:null,operatingMargin:null,debt:null,pe:null,pb:null,yield:null,foreign:null,trust:null,dealer:null,marginChange:null};const f=calculateForecast(historicalStock,ind),pred=directionFromForecast(f),future=history[i+5],ret=(future.close/slice.at(-1).close-1)*100,actual=directionFromReturn(ret);samples.push({date:slice.at(-1).date,pred,actual,ret:+ret.toFixed(2),correct:pred===actual,confidence:f.confidence})}
  const correct=samples.filter(x=>x.correct).length,returns=samples.map(x=>x.ret),result={samples,count:samples.length,hitRate:samples.length?correct/samples.length*100:null,avgReturn:mean(returns),avgWin:mean(samples.filter(x=>x.ret>0).map(x=>x.ret)),avgLoss:mean(samples.filter(x=>x.ret<0).map(x=>x.ret))};S.backtestCache.set(key,result);return result
}

function objectRows(value){
  if(Array.isArray(value))return value;
  if(value&&typeof value==='object')return Object.entries(value).map(([key,row])=>({key,...(row&&typeof row==='object'?row:{value:row})}));
  return[]
}
function firstValue(row,keys){for(const key of keys)if(row?.[key]!=null&&row[key]!=='')return row[key];return null}
function disclaimer(){return`<div class="disclaimer">${DISCLAIMER}</div>`}
function metric(label,value,note=''){return`<div class="metric"><small>${label}</small><b>${value}</b>${note?`<em>${note}</em>`:''}</div>`}
function valueOrReason(v,suffix='',reason='API 未回傳'){return v==null?reasonDash(reason):`${fmt(v)}${suffix}`}
function sourceDateSummary(){
  const dates=S.sourceDates||{},price=dates.price?.latest||S.date||'—',institutional=dates.institutional?.latest||'尚未提供',margin=dates.margin?.latest||'尚未提供';
  return`行情 ${price} · 法人 ${institutional} · 融資券 ${margin}`
}
function etfSnapshotScore(stock){const volume=Math.max(0,Math.log10(Math.max(stock.volume||0,1))-2)*13,value=Math.max(0,Math.log10(Math.max(stock.value||0,1))-6)*8,momentum=clamp((stock.change||0)*4+10,0,24),chip=stock.inst!=null&&stock.volume?clamp(stock.inst/stock.volume*25+7,0,18):0,dividend=stock.yield==null?0:clamp(stock.yield*2,0,12);return clamp(Math.round(volume+value+momentum+chip+dividend),0,100)}
function groupedHomeRows(group){
  if(typeof globalThis.twssGroupRanking==='function')return globalThis.twssGroupRanking(group,5);
  const rows=S.stocks.filter(stock=>instrumentGroup(stock)===group);
  if(group==='etf')return rows.filter(stock=>(stock.volume||0)>=500).map(stock=>({stock,score:etfSnapshotScore(stock)})).sort((a,b)=>b.score-a.score).slice(0,5);
  return rows.filter(opportunityEligible).map(stock=>({stock,score:opportunityScore(stock)})).sort((a,b)=>b.score-a.score).slice(0,5)
}

function homePage(){
  const env=marketEnvironment(),rank=(title,rows,value)=>`<div class="card"><h3>${title}</h3><div class="rank-list">${rows.slice(0,5).map((item,i)=>{const stock=item.stock||item;return`<div class="rank clickable" data-detail="${stock.symbol}"><b>${i+1}</b><span><b>${stock.name}</b><small class="muted"> ${stock.symbol}</small></span><b class="${cls(stock.change)}">${value(item,stock)}</b></div>`}).join('')||'<div class="muted">目前沒有符合最低流動性與資料條件的標的</div>'}</div></div>`;
  const rev=[...S.stocks].filter(x=>instrumentGroup(x)!=='etf'&&x.rev!=null).sort((a,b)=>b.rev-a.rev),inst=[...S.stocks].filter(x=>x.inst!=null).sort((a,b)=>b.inst-a.inst),listed=groupedHomeRows('listed'),otc=groupedHomeRows('otc'),etf=groupedHomeRows('etf');
  const counts={listed:S.stocks.filter(x=>instrumentGroup(x)==='listed').length,otc:S.stocks.filter(x=>instrumentGroup(x)==='otc').length,etf:S.stocks.filter(x=>instrumentGroup(x)==='etf').length};
  return`<h2>盤後市場儀表板</h2><div class="muted">官方盤後資料整理，不是即時報價。</div>
  <div class="grid">${metric('最新日期',S.date||'—')}${metric('上市股票',fmt(counts.listed,0))}${metric('上櫃股票',fmt(counts.otc,0))}${metric('ETF',fmt(counts.etf,0))}</div>
  <div class="card accent"><div class="head"><div><small class="muted">大盤環境</small><div class="price">${env.label}</div><div class="muted">上漲 ${env.up} · 下跌 ${env.down} · 平盤 ${env.flat}</div></div><div><small class="muted">多頭家數比</small><div class="score">${fmt(env.breadth,0)}%</div><div class="muted">平均漲跌 ${pct(env.avgChange)}</div></div></div><div class="grid" style="margin-top:10px">${metric('市場成交量',`${fmt(env.totalVolume,0)} 張`)}${metric('外資合計',`${fmt(env.foreign,0)} 張`)}${metric('三大法人合計',`${fmt(env.inst,0)} 張`)}${metric('環境信心',`${env.confidence}%`)}</div></div>
  <div class="card"><h3>產業相對強弱</h3><div class="rank-list">${env.industries.slice(0,6).map((x,i)=>`<div class="rank"><b>${i+1}</b><span><b>${x.industry}</b><small class="muted"> ${x.count} 檔 · 上漲家數 ${fmt(x.breadth,0)}%</small></span><b class="${cls(x.avgChange)}">${pct(x.avgChange)}</b></div>`).join('')}</div></div>
  <div class="notice"><b>分組排名</b><br>上市、上櫃與 ETF 使用各自適用因子，只與同組商品比較，不會混在同一個名次。</div>
  ${rank('上市機會榜',listed,item=>`${item.score} 分`)}${rank('上櫃機會榜',otc,item=>`${item.score} 分`)}${rank('ETF 觀察榜',etf,item=>`${item.score} 分`)}${rank('月營收年增排行（股票）',rev,(item,stock)=>pct(stock.rev))}${rank('三大法人買超排行',inst,(item,stock)=>`${fmt(stock.inst,0)} 張`)}${disclaimer()}`
}

function opportunityCard(stock){
  return`<article class="card accent clickable" data-detail="${stock.symbol}"><div class="head"><div><b>${stock.name}</b><div class="muted">${stock.symbol} · ${stock.industry}</div></div><div><small class="muted">機會分數</small><div class="score">${opportunityScore(stock)}</div></div></div><div><span class="price">${fmt(stock.close)}</span> <b class="${cls(stock.change)}">${pct(stock.change)}</b></div><div class="grid">${metric('月營收年增',pct(stock.rev),stock.revPeriod||'最新公開月')}${metric('月營收月增',pct(stock.revMom))}${metric(stock.roeEstimated?'年化推估 ROE':'ROE',stock.roe==null?reasonDash('API 未回傳'):`${fmt(stock.roe)}%`,stock.roePeriod||'')}${metric('本益比',valueOrReason(stock.pe))}</div><div class="rules" style="margin-top:10px"><span>成交量 ${fmt(stock.volume,0)} 張</span>${stock.foreign!=null?`<span>外資 ${fmt(stock.foreign,0)} 張</span>`:''}<span>${stock.industry}</span></div><div class="row" style="margin-top:10px"><button class="btn grow" data-forecast="${stock.symbol}">深度預測</button><button class="btn secondary" data-watch="${stock.symbol}">${isWatched(stock.symbol)?'★ 已自選':'＋自選'}</button></div></article>`
}
function opportunitiesPage(){
  const selected=S.stocks.filter(opportunityEligible).sort((a,b)=>opportunityScore(b)-opportunityScore(a));
  return`<h2>機會股</h2><p class="muted">月營收成長為核心，再綜合財報品質、估值、法人與流動性固定計分。</p><div class="card"><h3>固定門檻</h3><div class="rules"><span>月營收年增 ≥ 10%</span><span>成交量 ≥ 500 張</span><span>本益比 ≤ 35</span><span>ROE ≥ 8%（有資料時）</span><span>排除已確認風險股</span></div></div>${selected.length?`<div class="list two-col">${selected.map(opportunityCard).join('')}</div>`:`<div class="card empty"><h3>目前沒有完整符合條件的股票</h3><p class="muted">可能是資料仍在載入，或目前沒有股票同時達到固定門檻。</p></div>`}${disclaimer()}`
}

function stockSearchResults(query,attr){
  const text=query.trim().toLowerCase();if(!text)return'';const rows=S.stocks.filter(x=>x.symbol.includes(text)||x.name.toLowerCase().includes(text)).slice(0,12);
  return rows.length?`<div class="search-results">${rows.map(x=>`<button class="search-result" ${attr}="${x.symbol}"><span><b>${x.name}</b><small class="muted"> ${x.symbol} · ${x.industry}</small></span><span class="${cls(x.change)}">${pct(x.change)}</span></button>`).join('')}</div>`:'<div class="muted" style="margin-top:10px">找不到符合的股票</div>'
}
function forecastPage(){
  const top=[...S.stocks].filter(x=>x.rev!=null).sort((a,b)=>opportunityScore(b)-opportunityScore(a)).slice(0,8);
  return`<h2>未來漲跌預測</h2><p class="muted">整合歷史日線、MA、RSI、MACD、布林通道、ATR、量價、基本面、法人籌碼、大盤與產業環境。</p><div class="notice"><b>僅供參考使用</b><br>${DISCLAIMER}</div><div class="card"><h3>搜尋股票</h3><div class="search-row"><input id="forecastSearch" value="${esc(S.forecastQuery)}" placeholder="輸入代號或名稱，例如 3702 大聯大"><button id="forecastSearchBtn" class="btn">搜尋</button></div>${stockSearchResults(S.forecastQuery,'data-forecast')}</div><div class="card"><h3>優先分析清單</h3><div class="rank-list">${top.map((x,i)=>`<div class="rank clickable" data-forecast="${x.symbol}"><b>${i+1}</b><span><b>${x.name}</b><small class="muted"> ${x.symbol}</small></span><b>${opportunityScore(x)} 分</b></div>`).join('')}</div></div>${disclaimer()}`
}

function predictionStats(){
  const rows=getPredictions(),evaluated=rows.filter(x=>x.evaluated_at),recent30=evaluated.filter(x=>(Date.now()-new Date(x.prediction_date).getTime())<=30*864e5),recent90=evaluated.filter(x=>(Date.now()-new Date(x.prediction_date).getTime())<=90*864e5);
  const rate=list=>list.length?list.filter(x=>x.is_correct).length/list.length*100:null;
  return{rows,evaluated,rate30:rate(recent30),rate90:rate(recent90),pending:rows.filter(x=>!x.evaluated_at).length}
}
function verifyPage(){
  const stats=predictionStats(),selected=S.verifySymbol?S.stocks.find(x=>x.symbol===S.verifySymbol):null,cached=selected?[...S.backtestCache.entries()].find(([k])=>k.startsWith(selected.symbol+'-'))?.[1]:null;
  return`<h2>預測驗證</h2><p class="muted">保存每次預測，五個交易日後比對實際結果；另提供不使用未來資料的技術面走勢回測。</p><div class="stat-strip">${metric('已評估',fmt(stats.evaluated.length,0))}${metric('待評估',fmt(stats.pending,0))}${metric('近 30 日命中率',stats.rate30==null?'尚無樣本':`${fmt(stats.rate30,1)}%`)}${metric('近 90 日命中率',stats.rate90==null?'尚無樣本':`${fmt(stats.rate90,1)}%`)}</div>
  <div class="card"><h3>選擇股票進行歷史驗證</h3><div class="search-row"><input id="verifySearch" value="${esc(S.verifyQuery)}" placeholder="股票代號或名稱"><button id="verifySearchBtn" class="btn">搜尋</button></div>${stockSearchResults(S.verifyQuery,'data-verify')}</div>
  ${selected?`<div class="card accent"><div class="head"><div><h3>${selected.name} ${selected.symbol}</h3><div class="muted">技術面走勢回測，每 5 個交易日取樣一次</div></div><button class="btn small-btn" id="runBacktest" data-symbol="${selected.symbol}">${cached?'重新回測':'開始回測'}</button></div>${cached?backtestHtml(cached):'<div class="muted">按下開始回測後，會讀取近 12 個月日線並驗證方向。</div>'}</div>`:''}
  <div class="card"><h3>最近預測紀錄</h3>${stats.rows.length?`<div class="table-wrap"><table><thead><tr><th>股票／日期</th><th>預測</th><th>信心</th><th>實際</th><th>結果</th></tr></thead><tbody>${stats.rows.slice(0,30).map(x=>`<tr><td>${x.stock_name||x.symbol}<br><small class="muted">${x.prediction_date}</small></td><td>${directionLabel(x.predicted_direction)}</td><td>${fmt(x.confidence,0)}%</td><td>${x.actual_return_pct==null?'待評估':pct(x.actual_return_pct)}</td><td>${x.evaluated_at?(x.is_correct?'<span class="tag">正確</span>':'<span class="tag bad">不符</span>'):'<span class="tag info">等待中</span>'}</td></tr>`).join('')}</tbody></table></div>`:'<div class="empty muted">尚未產生預測紀錄。開啟任一股票的深度預測後會自動保存。</div>'}</div>
  <div class="notice">命中率只反映既有樣本，樣本不足或市場狀態改變時，不代表未來仍有相同表現。</div>${disclaimer()}`
}
function directionLabel(value){return value==='up'?'偏多':value==='down'?'偏空':'震盪'}
function backtestHtml(b){return`<div class="grid" style="margin-top:12px">${metric('回測樣本',fmt(b.count,0))}${metric('方向命中率',b.hitRate==null?'—':`${fmt(b.hitRate,1)}%`)}${metric('樣本平均報酬',pct(b.avgReturn))}${metric('平均獲利／虧損',`${pct(b.avgWin)} / ${pct(b.avgLoss)}`)}</div><div class="table-wrap" style="margin-top:10px"><table><thead><tr><th>日期</th><th>預測</th><th>5 日報酬</th><th>結果</th></tr></thead><tbody>${b.samples.slice(-12).reverse().map(x=>`<tr><td>${x.date}</td><td>${directionLabel(x.pred)}</td><td class="${cls(x.ret)}">${pct(x.ret)}</td><td>${x.correct?'✓':'×'}</td></tr>`).join('')}</tbody></table></div><div class="muted small" style="margin-top:8px">此回測只使用當時之前的價格與成交量，不套用現在的月營收或財報資料，避免偷看未來。</div>`}

function journalStats(){const all=getJournal(),closed=all.filter(x=>x.return_pct!=null),wins=closed.filter(x=>x.return_pct>0),followed=all.filter(x=>x.followed_plan!=null);return{all,closed,winRate:closed.length?wins.length/closed.length*100:null,avgReturn:mean(closed.map(x=>x.return_pct)),followRate:followed.length?followed.filter(x=>x.followed_plan).length/followed.length*100:null}}
function minePage(){
  return`<h2>我的</h2><div class="segmented"><button data-mine="watch" class="${S.mineSub==='watch'?'active':''}">自選清單</button><button data-mine="journal" class="${S.mineSub==='journal'?'active':''}">投資紀錄</button></div>${S.mineSub==='watch'?watchSection():journalSection()}${disclaimer()}`
}
function watchSection(){
  const items=getWatchlist();
  const rows=items.map(item=>({item,stock:S.stocks.find(x=>x.symbol===item.symbol)})).filter(x=>x.stock);
  if(!rows.length)return '<div class="card empty"><h3>尚未加入自選股票</h3><p class="muted">可在機會股或股票詳細頁加入。</p></div>';
  return `<div class="list two-col">${rows.map(({item,stock})=>{
    const gain=item.addedPrice&&stock.close?(stock.close/item.addedPrice-1)*100:null;
    return `<div class="card clickable" data-detail="${stock.symbol}"><div class="head"><div><b>${stock.name}</b><div class="muted">${stock.symbol} · ${stock.industry}</div></div><button class="icon-btn" data-watch="${stock.symbol}">移除</button></div><div class="grid">${metric('目前價格',fmt(stock.close))}${metric('加入後漲跌',`<span class="${cls(gain)}">${pct(gain)}</span>`)}${metric('月營收年增',pct(stock.rev))}${metric('機會分數',opportunityScore(stock))}</div><button class="btn" data-forecast="${stock.symbol}" style="width:100%;margin-top:10px">查看趨勢預測</button></div>`;
  }).join('')}</div>`;
}
function journalSection(){
  const stats=journalStats();
  const header=`<div class="stat-strip">${metric('紀錄筆數',fmt(stats.all.length,0))}${metric('已完成交易',fmt(stats.closed.length,0))}${metric('勝率',stats.winRate==null?'尚無樣本':`${fmt(stats.winRate,1)}%`)}${metric('遵守計畫率',stats.followRate==null?'尚無資料':`${fmt(stats.followRate,1)}%`)}</div><div class="row"><button id="newJournal" class="btn grow">＋新增投資紀錄</button><button id="exportJournal" class="btn secondary">匯出 JSON</button></div>`;
  if(!stats.all.length)return `${header}<div class="card empty"><h3>尚未建立投資紀錄</h3><p class="muted">記錄當時理由、預期、風險與結果，之後才能檢查自己是否遵守計畫。</p></div>`;
  return `${header}<div class="list">${stats.all.map(x=>`<div class="card journal-item ${x.action}"><div class="head"><div><b>${x.stock_name||x.symbol} ${x.symbol}</b><div class="muted">${x.entry_date} · ${actionLabel(x.action)} · ${horizonLabel(x.horizon)}</div></div>${x.return_pct!=null?`<b class="${cls(x.return_pct)}">${pct(x.return_pct)}</b>`:''}</div>${x.thesis?`<p>${esc(x.thesis)}</p>`:''}<div class="rules">${x.risk_plan?`<span>風險：${esc(x.risk_plan)}</span>`:''}${x.target_plan?`<span>目標：${esc(x.target_plan)}</span>`:''}${x.followed_plan!=null?`<span>遵守計畫：${x.followed_plan?'是':'否'}</span>`:''}</div><div class="row" style="margin-top:10px"><button class="btn secondary" data-edit-journal="${x.local_id||x.id}">編輯</button><button class="btn danger" data-delete-journal="${x.local_id||x.id}">刪除</button></div></div>`).join('')}</div>`;
}
function actionLabel(a){return({observe:'觀察',buy:'買入紀錄',sell:'賣出紀錄',review:'事後檢討'})[a]||a}
function horizonLabel(h){return({short:'短線 1–5 日',swing:'波段 1–4 週',medium:'中期 1–6 月',long:'長期 6 月以上'})[h]||'未設定期間'}

function sparkline(rows){const values=rows.slice(-60).map(r=>r.close).filter(v=>v!=null);if(values.length<2)return'';const w=600,h=84,min=Math.min(...values),max=Math.max(...values),range=max-min||1;const points=values.map((v,i)=>`${i/(values.length-1)*w},${h-(v-min)/range*(h-8)-4}`).join(' '),area=`0,${h} ${points} ${w},${h}`;return`<svg class="sparkline" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><polygon class="area" points="${area}"></polygon><polyline points="${points}"></polyline></svg>`}
function probabilitySection(f){return`<div class="prob-grid">${[['上漲',f.up,'up','bar-up'],['震盪',f.neutral,'neutral','bar-neutral'],['下跌',f.down,'down','bar-down']].map(([label,value,color,bar])=>`<div class="prob-box"><small class="muted">${label}機率</small><b class="${color}">${value}%</b><div class="progress" role="progressbar" aria-label="${label}機率" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${value}"><span class="${bar}" style="width:${value}%"></span></div></div>`).join('')}</div>`}
function factorSection(f){const rows=[['技術面',f.technical,55],['基本面',f.fundamental,35],['籌碼面',f.chip,20],['估值面',f.valuation,15]];return`<div class="factor-list">${rows.map(([label,value,max])=>{const width=clamp((value+max)/(max*2)*100,0,100);return`<div class="factor"><span>${label}</span><div class="track" role="progressbar" aria-label="${label}評估位置" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${fmt(width,0)}"><span style="width:${width}%"></span></div><b class="${cls(value)}">${value>0?'+':''}${fmt(value,1)}</b></div>`}).join('')}</div>`}
function scenarioHtml(stock,forecast,indicators){return scenarioAnalysis(stock,forecast,indicators).map(s=>`<div class="card scenario ${s.type}"><div class="head"><div><b>${s.title}</b><div class="muted">觸發條件：${s.trigger}</div></div><b>${s.prob}%</b></div><div class="price">${fmt(s.range[0])}～${fmt(s.range[1])}</div><div class="muted">5 個交易日情境區間，非價格保證。</div></div>`).join('')}
function marketIndustryHtml(stock){const env=marketEnvironment(),industry=env.industries.find(x=>x.industry===stock.industry);return`<div class="grid">${metric('大盤環境',env.label)}${metric('多頭家數比',`${fmt(env.breadth,0)}%`)}${metric(`${stock.industry}平均漲跌`,industry?pct(industry.avgChange):reasonDash('同業不足'))}${metric(`${stock.industry}上漲家數`,industry?`${fmt(industry.breadth,0)}%`:reasonDash('同業不足'))}${metric('市場外資合計',`${fmt(env.foreign,0)} 張`)}${metric('產業外資合計',industry?`${fmt(industry.foreign,0)} 張`:reasonDash('同業不足'))}</div>`}
function deepRowForStock(stock){
  const cached=S.deepCache.get(stock.symbol);if(cached&&!(cached instanceof Promise))return cached;
  const snapshot=typeof globalThis.twssUltimateSnapshot==='function'?globalThis.twssUltimateSnapshot():null;
  return Object.values(snapshot?.groups||{}).flat().find(row=>String(row?.stock?.symbol||'')===String(stock.symbol))||null
}
function deepPeerAndTrend(stock){
  const row=deepRowForStock(stock),context=row?.context||row?.analysis?.context||{};
  return{context,peer:context.peer||row?.peer||row?.analysis?.peer||null,trend:context.trend||row?.trend||row?.result?.trend||row?.analysis?.trend||null}
}
function trendHtml(stock){
  const {trend}=deepPeerAndTrend(stock),status=String(trend?.status||'').toLowerCase(),history=[...(Array.isArray(trend?.series)?trend.series:Array.isArray(trend?.history)?trend.history:[])].sort((a,b)=>String(b.date||'').localeCompare(String(a.date||'')));
  const current=history[0]||{},previous=history[1]||{},currentRank=safe(trend?.currentRank??trend?.rank??current.rank),previousRank=safe(trend?.previousRank??previous.rank);
  const rankDelta=safe(trend?.rankDelta??(currentRank!=null&&previousRank!=null?previousRank-currentRank:null)),scoreDelta=safe(trend?.scoreDelta??(safe(current.score)!=null&&safe(previous.score)!=null?safe(current.score)-safe(previous.score):null));
  const enough=!['accumulating','insufficient','pending'].includes(status)&&(rankDelta!=null||scoreDelta!=null||history.length>=2||previousRank!=null);
  if(!enough)return`<div class="card"><div class="head"><div><b>歷史分數累積中</b><div class="muted">至少需要兩個不同交易日，才顯示排名與分數變化。</div></div><span class="tag warn">累積中</span></div>${history.length?`<div class="muted small">目前 ${history.length} 份有效紀錄</div>`:''}</div>`;
  const change=value=>value==null?'—':`${value>0?'+':''}${fmt(value,1)}`;
  return`<div class="card"><div class="grid">${metric('目前排名',currentRank==null?'—':`第 ${fmt(currentRank,0)} 名`,previousRank==null?'':`前期第 ${fmt(previousRank,0)} 名`)}${metric('排名變動',rankDelta==null?'—':`${rankDelta>0?'+':''}${fmt(rankDelta,0)} 名`)}${metric('分數變動',change(scoreDelta))}${metric('歷史紀錄',`${Math.max(history.length,safe(trend?.count??trend?.finalDateCount)||0)} 份`)}</div></div>`
}
function peerHtml(stock){
  const {peer,context}=deepPeerAndTrend(stock),strictMarket=firstValue(peer,['market','marketLabel']),expectedGroup=instrumentGroup(stock),peerGroup=String(firstValue(peer,['group','marketGroup'])||context?.group||'').toLowerCase();
  if(!peer||strictMarket&&String(strictMarket)!==String(stock.market)||peerGroup&&['listed','otc','etf'].includes(peerGroup)&&peerGroup!==expectedGroup)return`<div class="card"><div class="head"><div><b>同市場比較累積中</b><div class="muted">只接受後端以相同市場建立的比較群；不使用全市場混合或前端臨時估算。</div></div><span class="tag warn">累積中</span></div></div>`;
  const rawRows=peer.metrics||peer.rows||peer.items||[],rows=objectRows(rawRows),basis=String(firstValue(peer,['scope','basis','method','fallbackType'])||'industry').toLowerCase();
  const fallback=Boolean(peer.fallback)||/group|market|fallback/.test(basis),groupLabel=firstValue(peer,['label','peerLabel','industry'])||(fallback?(expectedGroup==='listed'?'上市同組':expectedGroup==='otc'?'上櫃同組':'ETF 同組'):(context?.industry||stock.industry));
  const count=firstValue(peer,['peerCount','count','sampleSize','total']);
  if(!rows.length)return`<div class="card"><div class="head"><div><b>同市場比較累積中</b><div class="muted">已辨識 ${esc(groupLabel)}，但可比較指標尚未達最低樣本數。</div></div><span class="tag warn">累積中</span></div></div>`;
  const labels={score:['機會分數',' 分'],revenue_avg3:['3 月營收年增','%'],revenue_acceleration:['營收加速度','%'],operating_margin:['營業利益率','%'],cash_conversion:['現金轉換',' 倍'],institutional_intensity:['法人買超強度','%'],relative_strength20:['20 日相對強弱','%'],volume_ratio:['量能比',' 倍'],atr_pct:['ATR 波動','%'],pe:['本益比',' 倍'],premium_discount:['折溢價','%']};
  return`<div class="card"><div class="row wrap peer-basis"><span class="tag ${fallback?'warn':''}">${fallback?'同市場分組備援':'同產業比較'}</span><span class="muted">${esc(groupLabel)}${count!=null?` · ${fmt(count,0)} 檔`:''} · 僅與${esc(stock.market||'同市場')}標的比較</span></div>${rows.map((row,index)=>{const key=firstValue(row,['key','metric']),mapped=labels[key]||[],label=firstValue(row,['label','name'])||mapped[0]||key||`指標 ${index+1}`,value=safe(firstValue(row,['value','stockValue','current'])),median=safe(firstValue(row,['median','peerMedian','benchmark'])),percentile=safe(firstValue(row,['percentile','percentileRank','rankPercentile'])),suffix=firstValue(row,['suffix','unit'])||mapped[1]||'',available=firstValue(row,['availableCount','sampleSize']);return`<div class="peer-row"><span>${esc(label)}</span><div>${percentile==null?'':`<div class="peer-track" role="progressbar" aria-label="${esc(label)}同市場百分位" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${fmt(clamp(percentile,0,100),0)}"><span style="width:${clamp(percentile,0,100)}%"></span></div>`}<small class="muted">同組中位數 ${median==null?'—':`${fmt(median)}${esc(suffix)}`}${available!=null?` · ${fmt(available,0)} 筆`:''}</small></div><b>${value==null?'—':`${fmt(value)}${esc(suffix)}`}<br><small class="muted">${percentile==null?'樣本累積中':`百分位 ${fmt(percentile,0)}%`}</small></b></div>`}).join('')}</div>`
}
function eventHtml(stock,indicators){const events=buildEvents(stock,indicators);return`<div class="card">${events.map(e=>`<div class="event"><div class="event-icon">${e.icon}</div><div><b>${e.title}</b><div class="muted">${e.detail}</div></div><span class="tag ${e.level==='bad'?'bad':e.level==='warn'?'warn':'info'}">${e.level==='bad'?'風險':e.level==='warn'?'注意':'事件'}</span></div>`).join('')}</div>`}

function detailHtml(stock,state){
  const indicators=state?.indicators||null,history=state?.rows||[],forecast=calculateForecast(stock,indicators);
  const historyLoading=state?.loading,historyError=state?.error;
  const isEtf=instrumentGroup(stock)==='etf',notApplicable=reasonDash('ETF 不適用'),revenueAmount=value=>value==null?reasonDash('官方未提供'):`${fmt(value/1000000,0)} 百萬元`;
  const periodLine=isEtf?'ETF 無公司層級月營收與財報指標':`月營收 ${S.fundDates?.revenue?.period||stock.revPeriod||'載入中'} · 財報 ${S.fundDates?.financials?.period||stock.roePeriod||'載入中'}`;
  const basicMetrics=isEtf?`${metric('商品類型','ETF')}${metric('殖利率',valueOrReason(stock.yield,'%'))}${metric('本益比',notApplicable)}${metric('股價淨值比',notApplicable)}${metric('月營收',notApplicable)}${metric('ROE',notApplicable)}`:`${metric('本益比',valueOrReason(stock.pe))}${metric('股價淨值比',valueOrReason(stock.pb))}${metric('殖利率',valueOrReason(stock.yield,'%'))}${metric('當月營收',revenueAmount(stock.revenue),stock.revPeriod||'')}${metric('最新季營業額',revenueAmount(stock.quarterRevenue),stock.quarterRevenuePeriod||stock.roePeriod||'')}${metric('上月營收',revenueAmount(stock.revenuePreviousMonth))}${metric('去年同月營收',revenueAmount(stock.revenueLastYearMonth))}${metric('本年累計營收',revenueAmount(stock.revenueYtd))}${metric('去年同期累計',revenueAmount(stock.revenueLastYearYtd))}${metric('月營收年增',stock.rev==null?reasonDash(stock.dataStatus?.revenueYoy==='not-applicable-prior-year-zero'?'去年同期為 0，不適用':'官方未提供'):pct(stock.rev))}${metric('月營收月增',stock.revMom==null?reasonDash('官方未提供'):pct(stock.revMom))}${metric('累計營收年增',stock.revYtd==null?reasonDash('官方未提供'):pct(stock.revYtd))}${metric('成長加速度',stock.revAcceleration==null?reasonDash('資料不足'):pct(stock.revAcceleration),'單月年增－累計年增')}${metric('EPS',valueOrReason(stock.eps))}${metric(stock.roeEstimated?'年化推估 ROE':'ROE',valueOrReason(stock.roe,'%'),stock.roePeriod||'')}${metric('毛利率',valueOrReason(stock.grossMargin,'%'))}${metric('營業利益率',valueOrReason(stock.operatingMargin,'%'))}${metric('淨利率',valueOrReason(stock.netMargin,'%'))}${metric('負債比',valueOrReason(stock.debt,'%'))}${metric('權益比率',valueOrReason(stock.equityRatio,'%'))}${metric('資料期間',stock.roePeriod||stock.revPeriod||'—')}`;
  return`<div class="modal"><div class="sheet"><button class="sheet-close" type="button">×</button><div class="head"><div><h2>${stock.name} ${stock.symbol}</h2><div class="muted">${stock.market} · ${stock.industry} · 行情 ${S.sourceDates?.price?.[stock.market==='上市'?'twse':'tpex']||S.date}</div></div><button class="btn secondary small-btn" data-watch="${stock.symbol}">${isWatched(stock.symbol)?'★ 已自選':'☆ 加入自選'}</button></div><div><span class="price">${fmt(stock.close)} 元</span> <b class="${cls(stock.change)}">${pct(stock.change)}</b></div><div class="notice"><b>各資料來源日期</b><br>${sourceDateSummary()}。${periodLine}。</div>
  ${historyLoading?'<div class="card"><div class="loading"><span class="spinner"></span>正在讀取歷史日線並計算技術指標…</div></div>':''}${historyError?`<div class="card warn-card"><b>歷史日線暫時無法取得</b><p class="muted">目前先使用基本面與籌碼進行低信心估計。${esc(historyError)}</p></div>`:''}${history.length?sparkline(history):''}
  <h3 class="section-title">未來漲跌預測（5 個交易日）</h3><div class="card accent"><div class="head"><div><small class="muted">判斷</small><div class="price">${forecast.shortLabel}</div><div class="muted">中期：${forecast.mediumLabel}</div></div><div><small class="muted">預測信心</small><div class="score">${forecast.confidence}%</div><div class="muted">資料完整度 ${forecast.completeness}%</div></div></div>${probabilitySection(forecast)}<div class="grid" style="margin-top:10px">${metric('5 日合理波動區間',`${fmt(forecast.expectedLow)}～${fmt(forecast.expectedHigh)}`,`推估 ±${fmt(forecast.expectedMove5,1)}%`)}${metric('綜合方向分數',`${forecast.composite>0?'+':''}${forecast.composite}`,'正值偏多、負值偏空')}</div></div><div class="notice"><b>僅供參考使用</b><br>${DISCLAIMER}</div>
  <h3 class="section-title">三種情境分析</h3>${scenarioHtml(stock,forecast,indicators)}
  <h3 class="section-title">大盤與產業環境</h3><div class="card">${marketIndustryHtml(stock)}</div>
  <h3 class="section-title">分數與排名變化</h3>${trendHtml(stock)}
  <h3 class="section-title">同業比較</h3>${peerHtml(stock)}
  <h3 class="section-title">重要事件與風險提醒</h3>${eventHtml(stock,indicators)}
  <h3 class="section-title">評估構成</h3><div class="card">${factorSection(forecast)}</div><div class="card"><h3>支持因素</h3>${forecast.positive.length?forecast.positive.map(x=>`<span class="tag">${x}</span>`).join(''):'<span class="muted">目前沒有明顯正向訊號</span>'}<h3 style="margin-top:14px">風險因素</h3>${forecast.negative.length?forecast.negative.map(x=>`<span class="tag warn">${x}</span>`).join(''):'<span class="muted">目前沒有明顯負向訊號</span>'}<h3 style="margin-top:14px">資料缺口</h3>${forecast.missing.length?forecast.missing.map(x=>`<span class="tag bad">${x}</span>`).join(''):'<span class="tag">主要資料完整</span>'}</div>
  <h3 class="section-title">技術面分析</h3><div class="grid three">${metric('MA5',valueOrReason(indicators?.ma5))}${metric('MA20',valueOrReason(indicators?.ma20))}${metric('MA60',valueOrReason(indicators?.ma60))}${metric('RSI 14',valueOrReason(indicators?.rsi14))}${metric('MACD',valueOrReason(indicators?.macd))}${metric('MACD 柱狀體',valueOrReason(indicators?.histogram))}${metric('ATR 14',valueOrReason(indicators?.atr14),indicators?.atrPct!=null?`${fmt(indicators.atrPct)}%`:'')}${metric('量能比 5/20',valueOrReason(indicators?.volumeRatio,' 倍'))}${metric('20 日動能',valueOrReason(indicators?.momentum20,'%'))}${metric('布林上軌',valueOrReason(indicators?.bollingerUpper))}${metric('布林中軌',valueOrReason(indicators?.bollingerMiddle))}${metric('布林下軌',valueOrReason(indicators?.bollingerLower))}${metric('20 日支撐',valueOrReason(indicators?.support))}${metric('20 日壓力',valueOrReason(indicators?.resistance))}${metric('歷史日線筆數',indicators?.rows==null?reasonDash('尚未取得'):fmt(indicators.rows,0))}</div>
  <h3 class="section-title">${isEtf?'ETF 指標':'基本面與估值'}</h3><div class="grid three">${basicMetrics}</div>${isEtf?'<div class="notice">ETF 是一籃子資產，不適用單一公司的月營收、EPS、ROE、本益比與負債比；排名改看流動性、20／60 日動能、法人、波動風險與殖利率。</div>':stock.roeEstimated?'<div class="notice">ROE 是依最新公開累計淨利與股東權益推算的年化值，並非官方直接公布的單一指標。</div>':''}
  <h3 class="section-title">籌碼與交易資訊</h3><div class="grid three">${metric('外資買賣超',stock.foreign==null?reasonDash('該資料日無資料'):`${fmt(stock.foreign,0)} 張`)}${metric('投信買賣超',stock.trust==null?reasonDash('該資料日無資料'):`${fmt(stock.trust,0)} 張`)}${metric('自營商買賣超',stock.dealer==null?reasonDash('該資料日無資料'):`${fmt(stock.dealer,0)} 張`)}${metric('三大法人合計',stock.inst==null?reasonDash('該資料日無資料'):`${fmt(stock.inst,0)} 張`)}${metric('融資增減',stock.marginChange==null?reasonDash('官方未提供'):`${fmt(stock.marginChange,0)} 張`)}${metric('融資餘額',stock.marginBalance==null?reasonDash('官方未提供'):`${fmt(stock.marginBalance,0)} 張`)}${metric('融券增減',stock.shortChange==null?reasonDash('官方未提供'):`${fmt(stock.shortChange,0)} 張`)}${metric('融券餘額',stock.shortBalance==null?reasonDash('官方未提供'):`${fmt(stock.shortBalance,0)} 張`)}${metric('成交量',stock.volume==null?reasonDash('API 未回傳'):`${fmt(stock.volume,0)} 張`)}${metric('開盤',valueOrReason(stock.open))}${metric('最高',valueOrReason(stock.high))}${metric('最低',valueOrReason(stock.low))}${metric('成交金額',stock.value==null?reasonDash('API 未回傳'):`${fmt(stock.value/100000000,2)} 億元`)}${metric('成交筆數',stock.transactions==null?reasonDash('API 未回傳'):fmt(stock.transactions,0))}${metric('收盤',valueOrReason(stock.close))}</div>
  <div class="row" style="margin-top:16px"><button class="btn grow" data-journal-stock="${stock.symbol}">新增投資紀錄</button><button class="btn secondary" data-verify-stock="${stock.symbol}">查看預測驗證</button></div>${disclaimer()}</div></div>`
}

async function openDetail(symbol,loadHistory=true){
  const stock=S.stocks.find(x=>x.symbol===symbol);if(!stock)return;S.detailSymbol=symbol;
  const cachedHistory=S.historyCache.get(symbol),resolvedHistory=cachedHistory&&!(cachedHistory instanceof Promise)?cachedHistory:null;
  let historyState=resolvedHistory?{...resolvedHistory,loading:false}:{loading:Boolean(loadHistory||cachedHistory instanceof Promise),rows:[]};
  const paint=()=>{if(S.detailSymbol!==symbol)return;const scrollTop=q('.sheet',modalRoot)?.scrollTop||0;modalRoot.innerHTML=detailHtml(stock,historyState);bindModal();const sheet=q('.sheet',modalRoot);if(sheet)sheet.scrollTop=scrollTop};
  paint();
  const tasks=[];
  const cachedDeep=S.deepCache.get(symbol);
  if(!(cachedDeep&&!(cachedDeep instanceof Promise))){
    const deepPromise=cachedDeep instanceof Promise?cachedDeep:getDeepAnalysis(symbol);
    tasks.push(Promise.resolve(deepPromise).then(()=>paint()).catch(()=>{}));
  }
  if(resolvedHistory){const f=calculateForecast(stock,resolvedHistory.indicators);recordPrediction(stock,f);evaluatePredictionsForSymbol(symbol,resolvedHistory.rows)}
  else{
    const historyPromise=cachedHistory instanceof Promise?cachedHistory:(loadHistory?getHistory(symbol):null);
    if(historyPromise)tasks.push(Promise.resolve(historyPromise).then(result=>{historyState={...result,loading:false};paint();const f=calculateForecast(stock,result.indicators);recordPrediction(stock,f);evaluatePredictionsForSymbol(symbol,result.rows)}).catch(error=>{historyState={loading:false,error:error.message,rows:[]};paint()}));
    else historyState={loading:false,rows:[]};
  }
  await Promise.allSettled(tasks);
}
function closeModal(){
  S.detailSymbol=null;modalRoot.innerHTML='';document.body.classList.remove('modal-open');
  const returnFocus=modalReturnFocus;modalReturnFocus=null;modalFocusPrimed=false;
  if(returnFocus?.isConnected)requestAnimationFrame(()=>returnFocus.focus({preventScroll:true}));
}

function toggleWatch(symbol){
  const list=getWatchlist(),index=list.findIndex(x=>x.symbol===symbol);
  if(index>=0)list.splice(index,1);else{const stock=S.stocks.find(x=>x.symbol===symbol);list.push({symbol,addedPrice:stock?.close??null,addedAt:new Date().toISOString(),note:''})}
  setWatchlist(list);render();if(S.detailSymbol)openDetail(S.detailSymbol,false)
}

function adminTime(value){
  if(!value)return'—';const date=new Date(value);return Number.isNaN(date.getTime())?esc(value):esc(date.toLocaleString('zh-TW',{hour12:false}))
}
function adminStatus(value){
  const status=String(value||'unknown').toLowerCase(),labels={healthy:'正常',ready:'完成',success:'成功',running:'執行中',pending:'等待中',partial:'部分完成',warning:'注意',error:'異常',failed:'失敗',building:'建立中',final:'已封存'};
  return{label:labels[status]||status,className:['healthy','ready','success','final'].includes(status)?'':(['error','failed'].includes(status)?'bad':'warn')}
}
function adminJobLabel(value){return({universe:'全市場更新',deep_listed:'上市深度驗證',deep_otc:'上櫃深度驗證',deep_etf:'ETF 深度驗證'})[value]||value||'未命名工作'}
function adminGroupLabel(value){return({listed:'上市',otc:'上櫃',etf:'ETF'})[value]||value||'全市場'}
function adminSourceLabel(value){return({price:'每日行情',revenue:'月營收',financial:'季度財報',institutional:'法人籌碼',margin:'融資融券',holdings:'集保持股',benchmark:'市場基準'})[value]||value||'資料來源'}
function adminDatasetLabel(value){return({price_history:'歷史日線',monthly_revenue:'月營收',quarterly_revenue:'季度營收',quarterly_financials:'季度財報',income:'損益表',balance:'資產負債表',cashflow:'現金流量表',cash_conversion:'盈餘現金轉換',institutional:'法人籌碼',margin:'融資融券',holdings:'集保持股',benchmark:'市場基準',etf_profile:'ETF 基本資料',etf_premium_discount:'ETF 折溢價',deep_refresh:'深度更新',deep_analysis:'深度分析'})[value]||value||'資料'}
function adminSourceHtml(row){
  const state=adminStatus(row.status),covered=safe(row.covered),missing=safe(row.missing),total=safe(row.total);
  return`<div class="admin-source"><div class="head"><div><b>${esc(row.label||adminSourceLabel(row.key))}</b><div class="muted">資料日期 ${esc(row.latest||'—')}</div></div><span class="tag ${state.className}">${esc(state.label)}</span></div><div class="muted small">涵蓋 ${covered==null?'—':fmt(covered,0)}${total==null?'':`／${fmt(total,0)}`}${missing==null?'':` · 缺漏 ${fmt(missing,0)}`}${row.reasonCode?` · ${esc(row.reasonCode)}`:''}</div></div>`
}
function adminGroupHtml(row){
  const progress=clamp(safe(row.ratio??row.progress)??0,0,100),state=adminStatus(row.status);
  return`<div class="admin-group"><div class="health-progress-label"><b>${esc(adminGroupLabel(row.key||row.group))}</b><span>${fmt(row.verified??row.processed??0,0)}／${fmt(row.eligible??row.total??0,0)}</span></div><div class="progress" role="progressbar" aria-label="${esc(adminGroupLabel(row.key||row.group))}進度" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${fmt(progress,0)}"><span style="width:${progress}%"></span></div><div class="row admin-meta"><span class="tag ${state.className}">${esc(state.label)}</span><span>${esc(row.dataDate||row.cycleDate||'—')}</span></div></div>`
}
function adminJobHtml(job){
  const progress=clamp(safe(job.progress)??(job.total?Number(job.processed||0)/Number(job.total)*100:0),0,100),state=adminStatus(job.status),details=job.details&&Object.keys(job.details).length?esc(JSON.stringify(job.details,null,2)):'';
  return`<article class="admin-job"><div class="head"><div><b>${esc(adminJobLabel(job.jobKey))}</b><div class="muted">${esc(adminGroupLabel(job.group))} · 週期 ${esc(job.cycleDate||'—')} · 游標 ${fmt(job.cursor??0,0)}</div></div><span class="tag ${state.className}">${esc(state.label)}</span></div><div class="health-progress-label"><span>${fmt(job.processed??0,0)}／${fmt(job.total??0,0)}</span><b>${fmt(progress,1)}%</b></div><div class="progress"><span style="width:${progress}%"></span></div><div class="admin-job-times"><span>最後成功 ${adminTime(job.lastSuccessAt)}</span><span>下次執行 ${adminTime(job.nextRunAt)}</span></div>${job.lastErrorPreview?`<div class="admin-error"><b>${esc(job.lastErrorCode||'sync_error')}</b><span>${esc(job.lastErrorPreview)}</span></div>`:''}${details?`<details class="admin-details"><summary>查看工作摘要</summary><pre>${details}</pre></details>`:''}</article>`
}
function adminTimelineHtml(event){
  const labels={sync_job:'同步工作',analysis_error:'分析錯誤',repair_pending:'等待修復',api_quota:'API 額度',ranking_cycle:'排行榜週期'},state=adminStatus(event.status);
  return`<div class="admin-event"><time>${adminTime(event.at)}</time><div><b>${esc(labels[event.type]||event.type||'事件')} · ${esc(event.key||'—')}</b><span>${esc(adminGroupLabel(event.group))}${event.units!=null?` · ${fmt(event.units,0)} 次`:''}${event.errorKind?` · ${esc(event.errorKind)}`:''}</span></div>${event.status?`<span class="tag ${state.className}">${esc(state.label)}</span>`:''}</div>`
}
function adminPage(){
  if(!S.isAdmin)return'<div class="card error-card"><h2>沒有管理員權限</h2><p class="muted">請使用已授權的管理員帳號登入。</p></div>';
  if(S.adminState==='loading'&&!S.adminLog)return'<div class="card empty"><div class="loading"><span class="spinner"></span>正在讀取管理員日誌…</div></div>';
  if(S.adminState==='error'&&!S.adminLog)return`<div class="card error-card"><h2>管理日誌暫時無法取得</h2><p class="muted">${esc(S.adminError||'請稍後再試。')}</p><button id="refreshAdminLog" class="btn">重新讀取</button></div>`;
  const data=S.adminLog||{},summary=data.summary||{},health=data.health||{},jobs=Array.isArray(data.jobs)?data.jobs:[],sources=objectRows(health.sources),groups=objectRows(health.groups),repairs=Array.isArray(data.repairQueue?.items)?data.repairQueue.items:[],missing=Array.isArray(data.missingData?.examples)?data.missingData.examples:[],timeline=Array.isArray(data.timeline)?data.timeline:[],quota=data.apiQuota||{};
  return`<div class="admin-hero"><div><small>ADMIN ONLY</small><h2>管理員後台日誌</h2><p>資料健康、同步工作、修復佇列與 API 使用狀態。此頁只保存在目前登入階段，不會寫入快取。</p></div><button id="refreshAdminLog" class="btn secondary" ${S.adminState==='loading'?'disabled':''}>${S.adminState==='loading'?'更新中…':'重新整理'}</button></div>
    <div class="admin-session"><span class="tag">管理員 ${esc(data.admin?.username||'已驗證')}</span><span>產生時間 ${adminTime(data.generatedAt)}</span></div>
    <div class="stat-strip admin-stats">${metric('待修復',fmt(summary.pendingRepairs??0,0))}${metric('分析錯誤',fmt(summary.analysisErrors??0,0))}${metric('失敗工作',fmt(summary.failedJobs??0,0))}${metric('執行中',fmt(summary.runningJobs??0,0))}${metric('完成分析',fmt(summary.readyAnalyses??0,0))}${metric('最新資料日',esc(summary.latestDataDate||health.dataDate||'—'))}</div>
    <section class="card"><div class="head"><div><h3>同步工作</h3><div class="muted">只顯示管理員可讀的工作狀態與遮罩後錯誤摘要</div></div><span class="status-pill ${adminStatus(health.overallStatus).className}">${esc(adminStatus(health.overallStatus).label)}</span></div><div class="admin-jobs">${jobs.length?jobs.map(adminJobHtml).join(''):'<div class="muted">目前沒有同步工作紀錄。</div>'}</div></section>
    <section class="card"><h3>市場分組與資料來源</h3><div class="admin-groups">${groups.length?groups.map(adminGroupHtml).join(''):'<div class="muted">尚無分組統計。</div>'}</div><div class="admin-sources">${sources.length?sources.map(adminSourceHtml).join(''):'<div class="muted">尚無來源統計。</div>'}</div></section>
    <section class="card"><div class="head"><div><h3>修復佇列</h3><div class="muted">等待退避 ${fmt(data.repairQueue?.waitingBackoff??0,0)} · 錯誤 ${fmt(data.repairQueue?.errors??0,0)}</div></div><span class="tag warn">${fmt(data.repairQueue?.pending??0,0)} 筆</span></div><div class="table-wrap"><table class="admin-table"><thead><tr><th>標的</th><th>市場／狀態</th><th>原因</th><th>下次重試</th></tr></thead><tbody>${repairs.length?repairs.slice(0,60).map(item=>`<tr><td><b>${esc(item.name||item.symbol||'—')}</b><br><small>${esc(item.symbol||'')}</small></td><td>${esc(adminGroupLabel(item.group))}<br><small>${esc(item.status||'—')}</small></td><td>${esc((item.repairReasons||[]).join('、')||item.errorKind||'待判定')}</td><td>${adminTime(item.nextRetryAt)}</td></tr>`).join(''):'<tr><td colspan="4" class="muted">目前沒有等待修復項目。</td></tr>'}</tbody></table></div></section>
    <section class="card"><div class="head"><div><h3>來源缺漏</h3><div class="muted">僅供管理員判斷修復優先順序</div></div><span class="tag info">${missing.length} 筆範例</span></div><div class="admin-missing">${missing.length?missing.slice(0,40).map(item=>`<div><b>${esc(item.name||item.symbol||'—')} ${esc(item.symbol||'')}</b><span>${esc(adminDatasetLabel(item.dataset))} · ${esc(item.reason||item.classification||'待判定')}</span></div>`).join(''):'<div class="muted">目前沒有來源缺漏範例。</div>'}</div></section>
    <section class="card"><div class="head"><div><h3>最近 60 分鐘 API 額度</h3><div class="muted">下一次釋放 ${adminTime(quota.nextReleaseAt)}</div></div><b>${fmt(quota.usedLast60Minutes??0,0)} 次</b></div><div class="rules">${objectRows(quota.byJob).map(row=>`<span>${esc(adminJobLabel(row.key))} ${fmt(row.value??0,0)}</span>`).join('')||'<span>尚無配額使用紀錄</span>'}</div></section>
    <section class="card"><h3>最近事件</h3><div class="admin-timeline">${timeline.length?timeline.slice(0,60).map(adminTimelineHtml).join(''):'<div class="muted">目前沒有事件。</div>'}</div></section>`
}
async function loadAdminLog(force=false){
  if(!S.isAdmin||!S.session||S.adminState==='loading'&&!force)return;
  S.adminState='loading';S.adminError='';render();
  try{
    if(!await refreshSession())throw Object.assign(new Error('unauthorized'),{status:401});
    S.adminLog=await sb('/rest/v1/rpc/twss_admin_operations_log',{method:'POST',body:{p_limit:60}});S.adminState='ready'
  }catch(error){
    S.adminLog=null;
    if(error.status===401||error.status===403||error.code==='42501'||/admin_required/i.test(error.message||'')){clearAdminState();updateAccountUi()}
    else{S.adminState='error';S.adminError='管理資料暫時無法取得，請稍後再試。'}
  }
  render()
}
function openAdminPage(){if(!S.isAdmin)return;closeModal();S.tab='admin';updateAccountUi();render();loadAdminLog()}

function render(){
  if(S.tab==='admin'&&!S.isAdmin)S.tab='home';
  qa('.bottom-nav button').forEach(button=>{const active=button.dataset.tab===S.tab;button.classList.toggle('active',active);if(active)button.setAttribute('aria-current','page');else button.removeAttribute('aria-current')});
  updateAccountUi();
  if(S.loading&&!S.stocks.length){app.innerHTML='<div class="card empty"><div class="loading"><span class="spinner"></span>正在載入官方盤後資料…</div></div>';bind();return}
  app.innerHTML=S.tab==='home'?homePage():S.tab==='opportunities'?opportunitiesPage():S.tab==='forecast'?forecastPage():S.tab==='verify'?verifyPage():S.tab==='admin'?adminPage():minePage();bind()
}

function bind(){
  qa('.bottom-nav button').forEach(button=>button.onclick=()=>{S.tab=button.dataset.tab;render()});
  qa('[data-detail]').forEach(element=>element.onclick=event=>{if(!event.target.closest('button'))openDetail(element.dataset.detail)});
  qa('[data-forecast]').forEach(element=>element.onclick=event=>{event.stopPropagation();openDetail(element.dataset.forecast)});
  qa('[data-watch]').forEach(button=>button.onclick=event=>{event.stopPropagation();toggleWatch(button.dataset.watch)});
  const forecastSearch=q('#forecastSearch');if(forecastSearch){forecastSearch.oninput=e=>S.forecastQuery=e.target.value;forecastSearch.onkeydown=e=>{if(e.key==='Enter'){S.forecastQuery=e.target.value;render()}}}
  q('#forecastSearchBtn')?.addEventListener('click',()=>{S.forecastQuery=q('#forecastSearch')?.value||'';render()});
  const verifySearch=q('#verifySearch');if(verifySearch){verifySearch.oninput=e=>S.verifyQuery=e.target.value;verifySearch.onkeydown=e=>{if(e.key==='Enter'){S.verifyQuery=e.target.value;render()}}}
  q('#verifySearchBtn')?.addEventListener('click',()=>{S.verifyQuery=q('#verifySearch')?.value||'';render()});
  q('#refreshAdminLog')?.addEventListener('click',()=>loadAdminLog(true));
  qa('[data-verify]').forEach(button=>button.onclick=()=>{S.verifySymbol=button.dataset.verify;S.verifyQuery='';render()});
  q('#runBacktest')?.addEventListener('click',async e=>{
    const symbol=e.currentTarget.dataset.symbol,stock=S.stocks.find(x=>x.symbol===symbol);e.currentTarget.disabled=true;e.currentTarget.textContent='回測中…';
    try{const history=await getHistory(symbol),result=runTechnicalBacktest(stock,history.rows);evaluatePredictionsForSymbol(symbol,history.rows);render()}catch(error){alert(`回測失敗：${error.message}`);render()}
  });
  qa('[data-mine]').forEach(button=>button.onclick=()=>{S.mineSub=button.dataset.mine;render()});
  q('#newJournal')?.addEventListener('click',()=>openJournalModal());
  q('#exportJournal')?.addEventListener('click',exportJournal);
  qa('[data-edit-journal]').forEach(button=>button.onclick=()=>openJournalModal(getJournal().find(x=>String(x.local_id||x.id)===String(button.dataset.editJournal))));
  qa('[data-delete-journal]').forEach(button=>button.onclick=()=>deleteJournal(button.dataset.deleteJournal));
}

function bindModal(){
  q('.modal',modalRoot)?.addEventListener('click',e=>{if(e.target.classList.contains('modal'))closeModal()});
  qa('[data-watch]',modalRoot).forEach(button=>button.onclick=e=>{e.stopPropagation();toggleWatch(button.dataset.watch)});
  qa('[data-journal-stock]',modalRoot).forEach(button=>button.onclick=()=>{const symbol=button.dataset.journalStock,stock=S.stocks.find(x=>x.symbol===symbol);openJournalModal(null,stock)});
  qa('[data-verify-stock]',modalRoot).forEach(button=>button.onclick=()=>{S.verifySymbol=button.dataset.verifyStock;S.tab='verify';closeModal();render()});
}

function exportJournal(){
  const blob=new Blob([JSON.stringify({exported_at:new Date().toISOString(),journal:getJournal()},null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=`台股智選-投資紀錄-${today()}.json`;a.click();URL.revokeObjectURL(url)
}
function deleteJournal(id){if(!confirm('確定刪除這筆紀錄？'))return;const list=getJournal().filter(x=>String(x.local_id||x.id)!==String(id));setJournal(list);render()}

function openJournalModal(record=null,stock=null){
  const r=record||{},selected=stock||S.stocks.find(x=>x.symbol===r.symbol),symbol=selected?.symbol||r.symbol||'',name=selected?.name||r.stock_name||'';
  modalRoot.innerHTML=`<div class="modal"><div class="sheet"><button class="sheet-close" type="button">×</button><h2>${record?'編輯':'新增'}投資紀錄</h2><div class="form-grid">
    <label>股票代號<input id="jSymbol" value="${esc(symbol)}" placeholder="例如 2330"></label>
    <label>股票名稱<input id="jName" value="${esc(name)}" placeholder="例如 台積電"></label>
    <label>日期<input id="jDate" type="date" value="${esc(r.entry_date||today())}"></label>
    <label>類型<select id="jAction"><option value="observe">觀察</option><option value="buy">買入紀錄</option><option value="sell">賣出紀錄</option><option value="review">事後檢討</option></select></label>
    <label>價格<input id="jPrice" type="number" step="0.01" value="${r.price??selected?.close??''}"></label>
    <label>數量（股或張，自行統一）<input id="jQty" type="number" step="0.01" value="${r.quantity??''}"></label>
    <label>預計持有時間<select id="jHorizon"><option value="">未設定</option><option value="short">短線 1–5 日</option><option value="swing">波段 1–4 週</option><option value="medium">中期 1–6 月</option><option value="long">長期 6 月以上</option></select></label>
    <label>當時情緒<input id="jEmotion" value="${esc(r.emotion||'')}" placeholder="冷靜、焦慮、追高…"></label>
  </div>
  <label>判斷理由<textarea id="jThesis" placeholder="當時為什麼關注或交易？">${esc(r.thesis||'')}</textarea></label>
  <label>風險計畫<textarea id="jRisk" placeholder="什麼條件代表判斷失效？">${esc(r.risk_plan||'')}</textarea></label>
  <label>目標計畫<textarea id="jTarget" placeholder="原先預期的目標或觀察區間">${esc(r.target_plan||'')}</textarea></label>
  <div class="form-grid"><label>出場價格<input id="jExitPrice" type="number" step="0.01" value="${r.exit_price??''}"></label><label>出場日期<input id="jExitDate" type="date" value="${esc(r.exit_date||'')}"></label></div>
  <label>結果檢討<textarea id="jResult" placeholder="實際發生什麼？下次要改進什麼？">${esc(r.result_note||'')}</textarea></label>
  <label>是否遵守原本計畫<select id="jFollow"><option value="">尚未評估</option><option value="true">有遵守</option><option value="false">未遵守</option></select></label>
  <button id="saveJournal" class="btn" style="width:100%;margin-top:12px">儲存紀錄</button></div></div>`;
  q('#jAction',modalRoot).value=r.action||'observe';q('#jHorizon',modalRoot).value=r.horizon||'';q('#jFollow',modalRoot).value=r.followed_plan==null?'':String(r.followed_plan);bindModal();
  q('#saveJournal',modalRoot).onclick=async()=>{
    const symbolValue=q('#jSymbol',modalRoot).value.trim(),price=safe(q('#jPrice',modalRoot).value),exitPrice=safe(q('#jExitPrice',modalRoot).value);if(!/^\d{4}$/.test(symbolValue)){alert('請輸入四碼股票代號');return}
    const item={...r,local_id:r.local_id||r.id||uid(),symbol:symbolValue,stock_name:q('#jName',modalRoot).value.trim(),entry_date:q('#jDate',modalRoot).value||today(),action:q('#jAction',modalRoot).value,price,quantity:safe(q('#jQty',modalRoot).value),horizon:q('#jHorizon',modalRoot).value||null,emotion:q('#jEmotion',modalRoot).value.trim(),thesis:q('#jThesis',modalRoot).value.trim(),risk_plan:q('#jRisk',modalRoot).value.trim(),target_plan:q('#jTarget',modalRoot).value.trim(),exit_price:exitPrice,exit_date:q('#jExitDate',modalRoot).value||null,result_note:q('#jResult',modalRoot).value.trim(),followed_plan:q('#jFollow',modalRoot).value===''?null:q('#jFollow',modalRoot).value==='true'};
    item.return_pct=price&&exitPrice?+((exitPrice/price-1)*100).toFixed(2):r.return_pct??null;const list=getJournal(),index=list.findIndex(x=>String(x.local_id||x.id)===String(item.local_id));if(index>=0)list[index]=item;else list.unshift(item);setJournal(list);upsertJournalCloud(item).catch(()=>{});closeModal();S.tab='mine';S.mineSub='journal';render()
  }
}

function openAccountModal(){
  if(S.session){modalRoot.innerHTML=`<div class="modal"><div class="sheet"><button class="sheet-close">×</button><h2>雲端帳戶</h2><div class="card"><div class="head"><div><b>${esc(S.session.user?.email||'已登入')}</b><div class="muted">${S.isAdmin?'已驗證為管理員':'一般使用者'}</div></div>${S.isAdmin?'<span class="tag">管理員</span>':''}</div><p class="muted">預測紀錄與投資紀錄會同步至 Supabase。自選清單目前仍保留在此裝置。</p>${S.isAdmin?'<button id="openAdminPage" class="btn admin-open">開啟管理員後台日誌</button>':''}<div class="row"><button id="syncCloud" class="btn secondary grow">立即同步</button><button id="logout" class="btn danger">登出</button></div></div><div class="muted">${esc(S.syncState)}</div></div></div>`;bindModal();q('#openAdminPage',modalRoot)?.addEventListener('click',openAdminPage);q('#syncCloud',modalRoot).onclick=cloudPull;q('#logout',modalRoot).onclick=logoutAccount;return}
  modalRoot.innerHTML=`<div class="modal"><div class="sheet"><button class="sheet-close">×</button><h2>登入台股智選</h2><p class="muted">登入後可同步預測與投資紀錄。</p><label>電子郵件<input id="authEmail" type="email" autocomplete="email"></label><label>密碼<input id="authPass" type="password" autocomplete="current-password" placeholder="至少 6 個字元"></label><div class="row" style="margin-top:12px"><button id="loginBtn" class="btn grow">登入</button><button id="signupBtn" class="btn secondary">建立帳戶</button></div><div id="authMsg" class="muted" style="margin-top:10px"></div></div></div>`;bindModal();
  const afterAuth=()=>{closeModal();render()};
  const act=async type=>{const email=q('#authEmail',modalRoot).value.trim(),password=q('#authPass',modalRoot).value,msg=q('#authMsg',modalRoot);if(!email||password.length<6){msg.textContent='請輸入有效電子郵件，密碼至少 6 個字元。';return}msg.textContent='處理中…';try{if(type==='login'){await login(email,password);afterAuth()}else{const ok=await signup(email,password);if(ok)afterAuth();else msg.textContent='驗證信已寄出，完成驗證後再登入。'}}catch(e){msg.textContent=e.message}};
  q('#loginBtn',modalRoot).onclick=()=>act('login');q('#signupBtn',modalRoot).onclick=()=>act('signup')
}

document.querySelector('#accountBtn').onclick=openAccountModal;
document.querySelector('#adminBtn').onclick=openAdminPage;
if('serviceWorker'in navigator)navigator.serviceWorker.register('/sw.js?v=17.3.0',{updateViaCache:'none'}).catch(()=>{});
initSession();render();loadStocks();
