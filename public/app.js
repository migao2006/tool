'use strict';

const EDGE='/api/market-data';
const CORE_SUPABASE_URL='https://gxwrczuwshndnjactrij.supabase.co';
const CORE_SUPABASE_KEY='sb_publishable_M8sNxTHUuH06DwQQprIaoA_A2z4Tg7G';
const TAIPEI_TIME_ZONE='Asia/Taipei';
const DISCLAIMER='機會排序依公開資料、可重現量化規則與資料完整度整理；AI 只協助說明，不決定排名。內容僅供研究參考，不構成投資建議、買賣邀約或獲利保證。';

const S={
  tab:'home',stocks:[],mode:'loading',date:'',fundStatus:'loading',fundPeriod:'',loading:true,
  historyCache:new Map(),historySignals:new Map(),deepCache:new Map(),detailSymbol:null,
  session:null,isAdmin:false,adminRoleChecked:false,watchlistGroupId:null,dataStatus:{},sourceDates:{},fundDates:{},syncState:'本機模式'
};

const app=document.querySelector('#app');
const modalRoot=document.querySelector('#modalRoot');
const q=(s,r=document)=>r.querySelector(s);
const qa=(s,r=document)=>[...r.querySelectorAll(s)];
let modalReturnFocus=null;
let modalFocusPrimed=false;
let scrollResetGeneration=0;
let initialHomeScrollPending=true;

if('scrollRestoration'in history)history.scrollRestoration='manual';
function resetPageScroll(){
  const generation=++scrollResetGeneration;
  const apply=()=>{
    if(generation!==scrollResetGeneration)return;
    window.scrollTo(0,0);
    document.documentElement.scrollTop=0;
    document.body.scrollTop=0;
  };
  apply();
  requestAnimationFrame(()=>{apply();requestAnimationFrame(apply)});
  setTimeout(apply,160)
}
function settleInitialHomeScroll(){
  if(!initialHomeScrollPending)return;
  initialHomeScrollPending=false;
  if(S.tab==='home')resetPageScroll()
}
window.addEventListener('pageshow',event=>{
  if(S.tab==='home'&&(event.persisted||initialHomeScrollPending))resetPageScroll()
});

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
function taipeiParts(value=new Date(),includeTime=false){
  const date=value instanceof Date?value:new Date(value);if(Number.isNaN(date.getTime()))return null;
  const options={timeZone:TAIPEI_TIME_ZONE,year:'numeric',month:'2-digit',day:'2-digit',...(includeTime?{hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}:{})};
  return Object.fromEntries(new Intl.DateTimeFormat('en-CA',options).formatToParts(date).map(part=>[part.type,part.value]))
}
const today=()=>{const parts=taipeiParts();return`${parts.year}-${parts.month}-${parts.day}`};
const uid=()=>crypto.randomUUID?crypto.randomUUID():`${Date.now()}-${Math.random().toString(16).slice(2)}`;
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const reasonDash=reason=>`—（${reason}）`;

function marketDateInfo(){
  const price=S.sourceDates?.price||{},listed=/^\d{4}-\d{2}-\d{2}$/.test(price.twse||'')?price.twse:'',otc=/^\d{4}-\d{2}-\d{2}$/.test(price.tpex||'')?price.tpex:'';
  const known=[listed,otc].filter(Boolean).sort(),aligned=Boolean(listed&&otc&&listed===otc&&price.aligned!==false);
  return{listed,otc,aligned,latest:known.at(-1)||S.date||'',common:price.common||S.date||(aligned?listed:'')}
}
function updateMarketHeader(){
  const label=q('#marketDate'),mode=q('#dataMode');if(!label||!mode)return;
  const dates=marketDateInfo();
  let warning=false;
  if(dates.listed&&dates.otc&&!dates.aligned){
    warning=true;label.textContent=`盤後行情 上市 ${dates.listed}／上櫃 ${dates.otc}（日期待對齊）`;mode.textContent='部分官方資料';
  }else{
    label.textContent=dates.common?`最新交易日 ${dates.common} · 盤後資料（非即時）`:'資料日期待補';
    mode.textContent=dates.aligned?'官方日期已核對':dates.listed||dates.otc||S.mode==='partial'?'部分官方資料':'資料載入中';
  }
  label.classList.toggle('date-warning',warning)
}

function readLocal(key,fallback=[]){try{return JSON.parse(localStorage.getItem(key)||JSON.stringify(fallback))}catch{return fallback}}
function writeLocal(key,value){localStorage.setItem(key,JSON.stringify(value))}
const USER_DATA_VERSION='v18';
const LEGACY_USER_DATA_KEYS=Object.freeze({watchlist:'twss-watchlist-v15',predictions:'twss-predictions-v15',journal:'twss-journal-v15'});
function userDataKey(kind,userId=sessionUserId()){return`twss-${kind}-${USER_DATA_VERSION}:${userId||'guest'}`}
function quarantineLegacyUserData(){
  if(localStorage.getItem('twss-user-data-migrated-v18')==='1')return;
  for(const [kind,legacyKey] of Object.entries(LEGACY_USER_DATA_KEYS)){
    const quarantineKey=`twss-legacy-${kind}-v15-backup`,legacy=localStorage.getItem(legacyKey);
    if(localStorage.getItem(quarantineKey)==null&&legacy!=null)localStorage.setItem(quarantineKey,legacy);
    localStorage.removeItem(legacyKey)
  }
  localStorage.setItem('twss-user-data-migrated-v18','1')
}
function getWatchlist(userId=sessionUserId()){return readLocal(userDataKey('watchlist',userId),[])}
function setWatchlist(v,userId=sessionUserId()){writeLocal(userDataKey('watchlist',userId),v)}
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
  const cached=readMarketBootCache();
  if(cached)applyMarketPayload(cached,'cache');
  else{S.loading=true;render()}
  const staticSnapshot=loadLatestSnapshot().then(payload=>{
    if(!S.stocks.length&&payload)applySnapshotBoot(payload);
    return payload
  }).catch(()=>null);
  try{
    const payload=await fetchJson(`${EDGE}?type=stocks`,120000);
    if(!Array.isArray(payload.stocks)||payload.stocks.length<20)throw new Error(payload.error||'盤後資料筆數不足');
    applyMarketPayload(payload,'live');writeMarketBootCache(payload);loadFundamentals();
  }catch(error){
    await staticSnapshot;
    if(S.stocks.length){S.loading=false;S.mode='partial';render();settleInitialHomeScroll();loadFundamentals();return}
    S.loading=false;app.innerHTML=`<div class="card error-card"><h3>股票資料載入失敗</h3><p class="muted">${esc(error.message)}</p><button id="retryLoad" class="btn">重新載入</button></div>`;q('#retryLoad').onclick=loadStocks;
  }
}

const MARKET_BOOT_CACHE='twss-market-boot-v20.2';
const MARKET_BOOT_MAX_AGE_MS=7*24*60*60*1000;
const BOOT_STOCK_FIELDS=['symbol','name','market','instrumentType','industry','close','change','open','high','low','volume','value','transactions','pe','pb','yield','revenue','revenuePreviousMonth','revenueLastYearMonth','revenueYtd','revenueLastYearYtd','rev','revMom','revYtd','revAcceleration','revPeriod','eps','roe','roeEstimated','roePeriod','grossMargin','operatingMargin','netMargin','debt','equityRatio','foreign','trust','dealer','inst','marginBalance','marginChange','shortBalance','shortChange','disp','full'];
function compactBootStock(stock){return Object.fromEntries(BOOT_STOCK_FIELDS.filter(key=>stock?.[key]!=null).map(key=>[key,stock[key]]))}
function readMarketBootCache(){try{const payload=JSON.parse(localStorage.getItem(MARKET_BOOT_CACHE)||'null'),age=Date.now()-Date.parse(payload?.cachedAt||'');return Array.isArray(payload?.stocks)&&payload.stocks.length>=20&&Number.isFinite(age)&&age>=0&&age<=MARKET_BOOT_MAX_AGE_MS?payload:null}catch{return null}}
function writeMarketBootCache(payload){try{localStorage.setItem(MARKET_BOOT_CACHE,JSON.stringify({...payload,stocks:payload.stocks.map(compactBootStock),cachedAt:new Date().toISOString()}))}catch{}}
function applyMarketPayload(payload,source='live'){
  S.stocks=payload.stocks.map(normalizeStock);S.mode=source==='live'?(payload.mode||'partial'):'partial';S.date=payload.date||'';S.dataStatus=payload.sourceStatus||{};S.sourceDates=payload.dates||{};S.loading=false;
  render();settleInitialHomeScroll()
}
function loadLatestSnapshot(){
  if(!globalThis.twssLatestSnapshotPromise)globalThis.twssLatestSnapshotPromise=fetch('/data/latest.json?schema=16.3',{cache:'force-cache',headers:{accept:'application/json'}}).then(response=>response.ok?response.json():null).catch(()=>null);
  return globalThis.twssLatestSnapshotPromise
}
function applySnapshotBoot(snapshot){
  const rows=Object.values(snapshot?.groups||{}).flat(),stocks=[...new Map(rows.map(row=>[String(row?.stock?.symbol||''),row?.stock]).filter(([symbol,stock])=>symbol&&stock)).values()];
  if(stocks.length<20)return false;
  const dates=snapshot.groupDates||{},date=snapshot.dataDate||Object.values(dates).filter(Boolean).sort().at(-1)||'';
  const aligned=Boolean(dates.listed&&dates.otc&&dates.listed===dates.otc);
  applyMarketPayload({stocks,date,mode:'partial',dates:{price:{twse:dates.listed||date,tpex:dates.otc||date,common:aligned?dates.listed:'',aligned}}},'snapshot');
  return true
}

async function loadFundamentals(){
  if(globalThis.twssV20Active||document.querySelector('script[src^="/v20.js"]')){S.fundStatus='deferred';return}
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
const CORE_SESSION_KEY='twss-core-session-v18';
const LEGACY_SHARED_SESSION_KEY='twss-supabase-session-v15';
const watchMutationQueues=new Map();
function sessionUserId(session=S.session){return session?.user?.id||decodeJwtSub(session?.access_token)||null}
function updateAccountUi(){const account=q('#accountBtn');if(account)account.textContent=S.session?'帳戶':'登入'}
function storeSession(session){
  const previousId=sessionUserId(),nextId=sessionUserId(session);
  if(previousId!==nextId){S.watchlistGroupId=null;S.isAdmin=false;S.adminRoleChecked=false}
  S.session=session;
  if(session)localStorage.setItem(CORE_SESSION_KEY,JSON.stringify(session));else localStorage.removeItem(CORE_SESSION_KEY);
  updateAccountUi()
}
async function coreSb(path,options={}){
  const headers={apikey:CORE_SUPABASE_KEY,'Content-Type':'application/json',...(options.headers||{})};
  if(options.auth!==false&&S.session?.access_token)headers.Authorization=`Bearer ${S.session.access_token}`;
  const r=await fetch(CORE_SUPABASE_URL+path,{method:options.method||'GET',headers,body:options.body===undefined?undefined:JSON.stringify(options.body),cache:'no-store'});
  let data=null;try{data=await r.json()}catch{}if(!r.ok){const error=new Error(data?.message||data?.error_description||data?.error||`HTTP ${r.status}`);error.status=r.status;error.code=data?.code||null;throw error}return data;
}
async function refreshSession(){
  if(!S.session)return false;if((S.session.expires_at||0)>Date.now()/1000+90)return true;
  if(!S.session.refresh_token){storeSession(null);return false}
  try{const s=await coreSb('/auth/v1/token?grant_type=refresh_token',{method:'POST',body:{refresh_token:S.session.refresh_token},auth:false});s.expires_at=Math.floor(Date.now()/1000)+(s.expires_in||3600);storeSession(s);return true}catch{storeSession(null);return false}
}
async function refreshCoreAdminRole(){
  S.isAdmin=false;S.adminRoleChecked=false;
  if(!S.session||!await refreshSession()){S.adminRoleChecked=true;return false}
  try{S.isAdmin=(await coreSb('/rest/v1/rpc/twss_is_admin',{method:'POST',body:{}}))===true}catch{S.isAdmin=false}
  S.adminRoleChecked=true;return S.isAdmin
}
async function login(email,password){const s=await coreSb('/auth/v1/token?grant_type=password',{method:'POST',body:{email,password},auth:false});s.expires_at=Math.floor(Date.now()/1000)+(s.expires_in||3600);storeSession(s);await refreshCoreAdminRole();await cloudPull()}
async function signup(email,password){const s=await coreSb(`/auth/v1/signup?redirect_to=${encodeURIComponent(location.origin)}`,{method:'POST',body:{email,password},auth:false});if(s?.access_token){s.expires_at=Math.floor(Date.now()/1000)+(s.expires_in||3600);storeSession(s);await refreshCoreAdminRole();await cloudPull();return true}return false}
async function cloudPull(){
  if(!await refreshSession())return;const userId=sessionUserId(),guestWatch=getWatchlist(null),accountWatch=getWatchlist(userId),pendingWatch=[...accountWatch.filter(x=>x._sync_state==='pending'),...guestWatch.map(item=>{const id=item.id||item.local_id||uid();return{...item,id,local_id:id,_sync_state:'pending'}})];S.syncState='同步中…';
  try{
    const [groups,watchlist]=await Promise.all([
      coreSb('/rest/v1/watchlist_groups?select=id,name,sort_order&order=sort_order.asc,id.asc'),
      coreSb('/rest/v1/watchlist_items?select=id,group_id,symbol,added_price,added_at,note&order=added_at.desc')
    ]);
    if(sessionUserId()!==userId)return;
    S.watchlistGroupId=groups?.[0]?.id||null;
    const cloudWatch=(watchlist||[]).map(x=>({id:x.id,local_id:x.id,groupId:x.group_id,symbol:String(x.symbol),addedPrice:x.added_price,addedAt:x.added_at,note:x.note||'',_sync_state:'synced'}));
    for(const item of pendingWatch)if(!cloudWatch.some(row=>row.symbol===item.symbol))cloudWatch.unshift(item);
    setWatchlist(cloudWatch,userId);
    const uniquePending=[...new Map(pendingWatch.map(item=>[String(item.symbol),item])).values()];
    const synced=await Promise.allSettled(uniquePending.map(item=>enqueueWatchMutation(userId,item.symbol,()=>upsertWatchlistCloud(item,userId))));
    if(guestWatch.length&&synced.every(result=>result.status==='fulfilled'))setWatchlist([],null);
    S.syncState=synced.some(result=>result.status==='rejected')?'部分自選尚待同步':'雲端已同步';render();
  }catch(e){if(sessionUserId()===userId)S.syncState=`同步失敗：${e.message}`}
}
async function ensureWatchlistGroup(owner=sessionUserId()){
  if(!owner||sessionUserId()!==owner)return null;if(S.watchlistGroupId)return S.watchlistGroupId;if(!await refreshSession()||sessionUserId()!==owner)return null;
  let groups=await coreSb('/rest/v1/watchlist_groups?select=id&order=sort_order.asc,id.asc&limit=1');
  if(sessionUserId()!==owner)return null;
  if(!groups?.length)groups=await coreSb('/rest/v1/watchlist_groups',{method:'POST',headers:{Prefer:'return=representation'},body:{user_id:owner,name:'我的自選',sort_order:0}});
  if(sessionUserId()===owner)S.watchlistGroupId=groups?.[0]?.id||null;return S.watchlistGroupId
}
async function upsertWatchlistCloud(record,owner=sessionUserId()){
  if(!owner||!S.session||sessionUserId()!==owner)return null;const groupId=await ensureWatchlistGroup(owner);if(!groupId||sessionUserId()!==owner)return null;const id=record.id||record.local_id||uid(),body={id,user_id:owner,group_id:groupId,symbol:record.symbol,added_price:record.addedPrice??null,added_at:record.addedAt||new Date().toISOString(),note:record.note||''};
  const rows=await coreSb('/rest/v1/watchlist_items?on_conflict=group_id,symbol',{method:'POST',headers:{Prefer:'resolution=merge-duplicates,return=representation'},body});const saved=rows?.[0];if(saved&&sessionUserId()===owner){const list=getWatchlist(owner),index=list.findIndex(x=>x.symbol===record.symbol);if(index>=0){list[index]={...record,id:saved.id,local_id:saved.id,groupId:saved.group_id,_sync_state:'synced'};setWatchlist(list,owner)}}return saved||null
}
function enqueueWatchMutation(owner,symbol,operation){
  const key=`${owner||'guest'}:${String(symbol)}`,previous=watchMutationQueues.get(key)||Promise.resolve();
  const current=previous.catch(()=>{}).then(operation);
  watchMutationQueues.set(key,current);
  current.finally(()=>{if(watchMutationQueues.get(key)===current)watchMutationQueues.delete(key)}).catch(()=>{});
  return current
}
function decodeJwtSub(token){try{return JSON.parse(atob(token.split('.')[1].replace(/-/g,'+').replace(/_/g,'/'))).sub}catch{return null}}
async function logoutAccount(){try{if(S.session?.access_token)await coreSb('/auth/v1/logout',{method:'POST'})}catch{}finally{storeSession(null);S.syncState='本機模式';closeModal();render()}}
async function initSession(){quarantineLegacyUserData();localStorage.removeItem(LEGACY_SHARED_SESSION_KEY);let saved=null;try{saved=JSON.parse(localStorage.getItem(CORE_SESSION_KEY)||'null')}catch{}storeSession(saved);if(S.session&&await refreshSession()){try{S.session.user=await coreSb('/auth/v1/user');storeSession(S.session)}catch{}await refreshCoreAdminRole();cloudPull()}else{S.adminRoleChecked=true;updateAccountUi()}}
globalThis.twssUserData=Object.freeze({storageKey:userDataKey});

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
  const dates=S.sourceDates||{},market=marketDateInfo(),price=market.aligned?(market.common||'日期待補'):(market.listed&&market.otc?`上市 ${market.listed}／上櫃 ${market.otc}`:dates.price?.latest||S.date||'日期待補'),institutional=dates.institutional?.latest||'尚未提供',margin=dates.margin?.latest||'尚未提供';
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
  const counts={listed:S.stocks.filter(x=>instrumentGroup(x)==='listed').length,otc:S.stocks.filter(x=>instrumentGroup(x)==='otc').length,etf:S.stocks.filter(x=>instrumentGroup(x)==='etf').length},market=marketDateInfo(),dateNote=market.aligned?'上市、上櫃已對齊':market.listed&&market.otc?`上市 ${market.listed}／上櫃 ${market.otc}`:'部分市場日期尚未提供';
  return`<h2>盤後市場儀表板</h2><div class="muted">官方盤後資料整理，不是即時報價。</div>
  <div class="grid">${metric('全市場資料日',market.common||S.date||'日期待補',dateNote)}${metric('上市股票',fmt(counts.listed,0))}${metric('上櫃股票',fmt(counts.otc,0))}${metric('ETF',fmt(counts.etf,0))}</div>
  <div class="card accent"><div class="head"><div><small class="muted">大盤環境</small><div class="price">${env.label}</div><div class="muted">上漲 ${env.up} · 下跌 ${env.down} · 平盤 ${env.flat}</div></div><div><small class="muted">多頭家數比</small><div class="score">${fmt(env.breadth,0)}%</div><div class="muted">平均漲跌 ${pct(env.avgChange)}</div></div></div><div class="grid" style="margin-top:10px">${metric('市場成交量',`${fmt(env.totalVolume,0)} 張`)}${metric('外資合計',`${fmt(env.foreign,0)} 張`)}${metric('三大法人合計',`${fmt(env.inst,0)} 張`)}${metric('環境信心',`${env.confidence}%`)}</div></div>
  <div class="card"><h3>產業相對強弱</h3><div class="rank-list">${env.industries.slice(0,6).map((x,i)=>`<div class="rank"><b>${i+1}</b><span><b>${x.industry}</b><small class="muted"> ${x.count} 檔 · 上漲家數 ${fmt(x.breadth,0)}%</small></span><b class="${cls(x.avgChange)}">${pct(x.avgChange)}</b></div>`).join('')}</div></div>
  <div class="notice"><b>分組排名</b><br>上市、上櫃與 ETF 使用各自適用因子，只與同組商品比較，不會混在同一個名次。</div>
  ${rank('上市機會榜',listed,item=>`${item.score} 分`)}${rank('上櫃機會榜',otc,item=>`${item.score} 分`)}${rank('ETF 觀察榜',etf,item=>`${item.score} 分`)}${rank('月營收年增排行（股票）',rev,(item,stock)=>pct(stock.rev))}${rank('三大法人買超排行',inst,(item,stock)=>`${fmt(stock.inst,0)} 張`)}${disclaimer()}`
}

function opportunityCard(stock){
  return`<article class="card accent clickable" data-detail="${stock.symbol}"><div class="head"><div><b>${stock.name}</b><div class="muted">${stock.symbol} · ${stock.industry}</div></div><div><small class="muted">機會分數</small><div class="score">${opportunityScore(stock)}</div></div></div><div><span class="price">${fmt(stock.close)}</span> <b class="${cls(stock.change)}">${pct(stock.change)}</b></div><div class="grid">${metric('月營收年增',pct(stock.rev),stock.revPeriod||'最新公開月')}${metric('月營收月增',pct(stock.revMom))}${metric(stock.roeEstimated?'年化推估 ROE':'ROE',stock.roe==null?reasonDash('API 未回傳'):`${fmt(stock.roe)}%`,stock.roePeriod||'')}${metric('本益比',valueOrReason(stock.pe))}</div><div class="rules" style="margin-top:10px"><span>成交量 ${fmt(stock.volume,0)} 張</span>${stock.foreign!=null?`<span>外資 ${fmt(stock.foreign,0)} 張</span>`:''}<span>${stock.industry}</span></div><div class="row" style="margin-top:10px"><button class="btn grow" data-analysis="${stock.symbol}">查看分析</button><button class="btn secondary" data-watch="${stock.symbol}">${isWatched(stock.symbol)?'★ 已自選':'＋自選'}</button></div></article>`
}
function opportunitiesPage(){
  const selected=S.stocks.filter(opportunityEligible).sort((a,b)=>opportunityScore(b)-opportunityScore(a));
  return`<h2>機會股</h2><p class="muted">月營收成長為核心，再綜合財報品質、估值、法人與流動性固定計分。</p><div class="card"><h3>固定門檻</h3><div class="rules"><span>月營收年增 ≥ 10%</span><span>成交量 ≥ 500 張</span><span>本益比 ≤ 35</span><span>ROE ≥ 8%（有資料時）</span><span>排除已確認風險股</span></div></div>${selected.length?`<div class="list two-col">${selected.map(opportunityCard).join('')}</div>`:`<div class="card empty"><h3>目前沒有完整符合條件的股票</h3><p class="muted">可能是資料仍在載入，或目前沒有股票同時達到固定門檻。</p></div>`}${disclaimer()}`
}

function stockSearchResults(query,attr){
  const text=query.trim().toLowerCase();if(!text)return'';const rows=S.stocks.filter(x=>x.symbol.includes(text)||x.name.toLowerCase().includes(text)).slice(0,12);
  return rows.length?`<div class="search-results">${rows.map(x=>`<button class="search-result" ${attr}="${x.symbol}"><span><b>${x.name}</b><small class="muted"> ${x.symbol} · ${x.industry}</small></span><span class="${cls(x.change)}">${pct(x.change)}</span></button>`).join('')}</div>`:'<div class="muted" style="margin-top:10px">找不到符合的股票</div>'
}
function minePage(){
  return`<h2>我的</h2><h3 class="section-title">自選清單</h3>${watchSection()}${disclaimer()}`
}
function watchSection(){
  const items=getWatchlist();
  const rows=items.map(item=>({item,stock:S.stocks.find(x=>x.symbol===item.symbol)})).filter(x=>x.stock);
  if(!rows.length)return '<div class="card empty"><h3>尚未加入自選股票</h3><p class="muted">可在機會股或股票詳細頁加入。</p></div>';
  return `<div class="list two-col">${rows.map(({stock})=>{
    return `<div class="card clickable" data-detail="${stock.symbol}"><div class="head"><div><b>${stock.name}</b><div class="muted">${stock.symbol} · ${stock.industry}</div></div><button class="icon-btn" data-watch="${stock.symbol}">移除</button></div><div class="grid">${metric('目前價格',fmt(stock.close))}${metric('當日漲跌',`<span class="${cls(stock.change)}">${pct(stock.change)}</span>`)}${metric('月營收年增',pct(stock.rev))}${metric('機會分數',opportunityScore(stock))}</div><button class="btn" data-analysis="${stock.symbol}" style="width:100%;margin-top:10px">查看分析</button></div>`;
  }).join('')}</div>`;
}
function sparkline(rows){const values=rows.slice(-60).map(r=>r.close).filter(v=>v!=null);if(values.length<2)return'';const w=600,h=84,min=Math.min(...values),max=Math.max(...values),range=max-min||1;const points=values.map((v,i)=>`${i/(values.length-1)*w},${h-(v-min)/range*(h-8)-4}`).join(' '),area=`0,${h} ${points} ${w},${h}`;return`<svg class="sparkline" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><polygon class="area" points="${area}"></polygon><polyline points="${points}"></polyline></svg>`}
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
  const indicators=state?.indicators||null,history=state?.rows||[];
  const historyLoading=state?.loading,historyError=state?.error;
  const isEtf=instrumentGroup(stock)==='etf',notApplicable=reasonDash('ETF 不適用'),revenueAmount=value=>value==null?reasonDash('官方未提供'):`${fmt(value/1000000,0)} 百萬元`;
  const periodLine=isEtf?'ETF 無公司層級月營收與財報指標':`月營收 ${S.fundDates?.revenue?.period||stock.revPeriod||'載入中'} · 財報 ${S.fundDates?.financials?.period||stock.roePeriod||'載入中'}`;
  const basicMetrics=isEtf?`${metric('商品類型','ETF')}${metric('殖利率',valueOrReason(stock.yield,'%'))}${metric('本益比',notApplicable)}${metric('股價淨值比',notApplicable)}${metric('月營收',notApplicable)}${metric('ROE',notApplicable)}`:`${metric('本益比',valueOrReason(stock.pe))}${metric('股價淨值比',valueOrReason(stock.pb))}${metric('殖利率',valueOrReason(stock.yield,'%'))}${metric('當月營收',revenueAmount(stock.revenue),stock.revPeriod||'')}${metric('最新季營業額',revenueAmount(stock.quarterRevenue),stock.quarterRevenuePeriod||stock.roePeriod||'')}${metric('上月營收',revenueAmount(stock.revenuePreviousMonth))}${metric('去年同月營收',revenueAmount(stock.revenueLastYearMonth))}${metric('本年累計營收',revenueAmount(stock.revenueYtd))}${metric('去年同期累計',revenueAmount(stock.revenueLastYearYtd))}${metric('月營收年增',stock.rev==null?reasonDash(stock.dataStatus?.revenueYoy==='not-applicable-prior-year-zero'?'去年同期為 0，不適用':'官方未提供'):pct(stock.rev))}${metric('月營收月增',stock.revMom==null?reasonDash('官方未提供'):pct(stock.revMom))}${metric('累計營收年增',stock.revYtd==null?reasonDash('官方未提供'):pct(stock.revYtd))}${metric('成長加速度',stock.revAcceleration==null?reasonDash('資料不足'):pct(stock.revAcceleration),'單月年增－累計年增')}${metric('EPS',valueOrReason(stock.eps))}${metric(stock.roeEstimated?'年化推估 ROE':'ROE',valueOrReason(stock.roe,'%'),stock.roePeriod||'')}${metric('毛利率',valueOrReason(stock.grossMargin,'%'))}${metric('營業利益率',valueOrReason(stock.operatingMargin,'%'))}${metric('淨利率',valueOrReason(stock.netMargin,'%'))}${metric('負債比',valueOrReason(stock.debt,'%'))}${metric('權益比率',valueOrReason(stock.equityRatio,'%'))}${metric('資料期間',stock.roePeriod||stock.revPeriod||'—')}`;
  return`<div class="modal"><div class="sheet"><button class="sheet-close" type="button">×</button><div class="head"><div><h2>${stock.name} ${stock.symbol}</h2><div class="muted">${stock.market} · ${stock.industry} · 行情 ${S.sourceDates?.price?.[stock.market==='上市'?'twse':'tpex']||S.date||'日期待補'}</div></div><button class="btn secondary small-btn" data-watch="${stock.symbol}">${isWatched(stock.symbol)?'★ 已自選':'☆ 加入自選'}</button></div><div><span class="price">${fmt(stock.close)} 元</span> <b class="${cls(stock.change)}">${pct(stock.change)}</b></div><div class="notice"><b>各資料來源日期</b><br>${sourceDateSummary()}。${periodLine}。</div>
  ${historyLoading?'<div class="card"><div class="loading"><span class="spinner"></span>正在讀取歷史日線並計算技術指標…</div></div>':''}${historyError?`<div class="card warn-card"><b>歷史日線暫時無法取得</b><p class="muted">目前先使用基本面與籌碼進行低信心估計。${esc(historyError)}</p></div>`:''}${history.length?sparkline(history):''}
  <h3 class="section-title">大盤與產業環境</h3><div class="card">${marketIndustryHtml(stock)}</div>
  <h3 class="section-title">分數與排名變化</h3>${trendHtml(stock)}
  <h3 class="section-title">同業比較</h3>${peerHtml(stock)}
  <h3 class="section-title">重要事件與風險提醒</h3>${eventHtml(stock,indicators)}
  <h3 class="section-title">閱讀重點</h3><div class="card"><p>先確認營收、法人與價格趨勢是否同方向，再查看下方風險提醒。指標只是線索，不能單獨代表好壞。</p></div>
  <h3 class="section-title">技術面分析</h3><div class="grid three">${metric('MA5',valueOrReason(indicators?.ma5))}${metric('MA20',valueOrReason(indicators?.ma20))}${metric('MA60',valueOrReason(indicators?.ma60))}${metric('RSI 14',valueOrReason(indicators?.rsi14))}${metric('MACD',valueOrReason(indicators?.macd))}${metric('MACD 柱狀體',valueOrReason(indicators?.histogram))}${metric('ATR 14',valueOrReason(indicators?.atr14),indicators?.atrPct!=null?`${fmt(indicators.atrPct)}%`:'')}${metric('量能比 5/20',valueOrReason(indicators?.volumeRatio,' 倍'))}${metric('20 日動能',valueOrReason(indicators?.momentum20,'%'))}${metric('布林上軌',valueOrReason(indicators?.bollingerUpper))}${metric('布林中軌',valueOrReason(indicators?.bollingerMiddle))}${metric('布林下軌',valueOrReason(indicators?.bollingerLower))}${metric('20 日支撐',valueOrReason(indicators?.support))}${metric('20 日壓力',valueOrReason(indicators?.resistance))}${metric('歷史日線筆數',indicators?.rows==null?reasonDash('尚未取得'):fmt(indicators.rows,0))}</div>
  <h3 class="section-title">${isEtf?'ETF 指標':'基本面與估值'}</h3><div class="grid three">${basicMetrics}</div>${isEtf?'<div class="notice">ETF 是一籃子資產，不適用單一公司的月營收、EPS、ROE、本益比與負債比；排名改看流動性、20／60 日動能、法人、波動風險與殖利率。</div>':stock.roeEstimated?'<div class="notice">ROE 是依最新公開累計淨利與股東權益推算的年化值，並非官方直接公布的單一指標。</div>':''}
  <h3 class="section-title">籌碼與交易資訊</h3><div class="grid three">${metric('外資買賣超',stock.foreign==null?reasonDash('該資料日無資料'):`${fmt(stock.foreign,0)} 張`)}${metric('投信買賣超',stock.trust==null?reasonDash('該資料日無資料'):`${fmt(stock.trust,0)} 張`)}${metric('自營商買賣超',stock.dealer==null?reasonDash('該資料日無資料'):`${fmt(stock.dealer,0)} 張`)}${metric('三大法人合計',stock.inst==null?reasonDash('該資料日無資料'):`${fmt(stock.inst,0)} 張`)}${metric('融資增減',stock.marginChange==null?reasonDash('官方未提供'):`${fmt(stock.marginChange,0)} 張`)}${metric('融資餘額',stock.marginBalance==null?reasonDash('官方未提供'):`${fmt(stock.marginBalance,0)} 張`)}${metric('融券增減',stock.shortChange==null?reasonDash('官方未提供'):`${fmt(stock.shortChange,0)} 張`)}${metric('融券餘額',stock.shortBalance==null?reasonDash('官方未提供'):`${fmt(stock.shortBalance,0)} 張`)}${metric('成交量',stock.volume==null?reasonDash('API 未回傳'):`${fmt(stock.volume,0)} 張`)}${metric('開盤',valueOrReason(stock.open))}${metric('最高',valueOrReason(stock.high))}${metric('最低',valueOrReason(stock.low))}${metric('成交金額',stock.value==null?reasonDash('API 未回傳'):`${fmt(stock.value/100000000,2)} 億元`)}${metric('成交筆數',stock.transactions==null?reasonDash('API 未回傳'):fmt(stock.transactions,0))}${metric('收盤',valueOrReason(stock.close))}</div>
  ${disclaimer()}</div></div>`
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
  if(resolvedHistory)historyState={...resolvedHistory,loading:false};
  else{
    const historyPromise=cachedHistory instanceof Promise?cachedHistory:(loadHistory?getHistory(symbol):null);
    if(historyPromise)tasks.push(Promise.resolve(historyPromise).then(result=>{historyState={...result,loading:false};paint()}).catch(error=>{historyState={loading:false,error:error.message,rows:[]};paint()}));
    else historyState={loading:false,rows:[]};
  }
  await Promise.allSettled(tasks);
}
function closeModal(){
  S.detailSymbol=null;modalRoot.innerHTML='';document.body.classList.remove('modal-open');
  const returnFocus=modalReturnFocus;modalReturnFocus=null;modalFocusPrimed=false;
  if(returnFocus?.isConnected)requestAnimationFrame(()=>returnFocus.focus({preventScroll:true}));
}

async function toggleWatch(symbol){
  const owner=sessionUserId(),list=getWatchlist(owner),index=list.findIndex(x=>x.symbol===symbol);
  if(index>=0){
    const [removed]=list.splice(index,1);setWatchlist(list,owner);render();if(S.detailSymbol)openDetail(S.detailSymbol,false);
    if(owner&&S.session){try{await enqueueWatchMutation(owner,symbol,async()=>{if(!await refreshSession()||sessionUserId()!==owner)throw new Error('登入已過期，自選刪除尚未同步');const groupId=removed.groupId||await ensureWatchlistGroup(owner);if(!groupId)throw new Error('找不到自選股群組');await coreSb(`/rest/v1/watchlist_items?group_id=eq.${encodeURIComponent(groupId)}&symbol=eq.${encodeURIComponent(symbol)}`,{method:'DELETE',headers:{Prefer:'return=minimal'}})})}catch(error){const restored=getWatchlist(owner);if(!restored.some(item=>item.symbol===symbol)){restored.splice(Math.min(index,restored.length),0,removed);setWatchlist(restored,owner)}if(sessionUserId()===owner){S.syncState=`自選同步失敗：${error.message}`;render()}}}
    return
  }
  const stock=S.stocks.find(x=>x.symbol===symbol),id=uid(),item={id,local_id:id,symbol,addedPrice:stock?.close??null,addedAt:new Date().toISOString(),note:'',_sync_state:owner&&S.session?'pending':'local'};list.push(item);setWatchlist(list,owner);render();if(S.detailSymbol)openDetail(S.detailSymbol,false);
  if(owner&&S.session)enqueueWatchMutation(owner,symbol,()=>upsertWatchlistCloud(item,owner)).catch(error=>{if(sessionUserId()===owner)S.syncState=`自選同步失敗：${error.message}`})
}

/* v18: the embedded administrator implementation is intentionally disabled.
   MARKET administration is available only from the standalone /admin page,
   whose session storage is isolated from this CORE-authenticated app.
function adminTime(value){
  if(!value)return'—';const parts=taipeiParts(value,true);return parts?`${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}:${parts.second}`:esc(value)
}
function adminStatus(value){
  const status=String(value||'unknown').toLowerCase(),labels={healthy:'正常',ready:'完成',success:'成功',running:'執行中',pending:'等待中',partial:'部分完成',warning:'注意',error:'異常',failed:'失敗',building:'建立中',final:'已封存'};
  return{label:labels[status]||status,className:['healthy','ready','success','final'].includes(status)?'ok':(['error','failed'].includes(status)?'bad':'warn')}
}
function latestCommonRankingDate(cycles){
  const byDate=new Map();for(const cycle of Array.isArray(cycles)?cycles:[]){if(cycle.status!=='final'||!['listed','otc','etf'].includes(cycle.group)||!cycle.scoreDate)continue;if(!byDate.has(cycle.scoreDate))byDate.set(cycle.scoreDate,new Set());byDate.get(cycle.scoreDate).add(cycle.group)}
  return[...byDate].filter(([,groups])=>groups.size===3).map(([date])=>date).sort().at(-1)||''
}
function adminDateSummary(data){
  const market=marketDateInfo(),backend=data.health?.dataDate||data.summary?.latestDataDate||'',analysis=latestCommonRankingDate(data.rankingCycles)||data.health?.scoreHistory?.latestCommonFinalDate||'',aligned=Boolean(market.aligned&&backend&&market.common===backend),scheduleMissing=data.schedule?.ready===false&&!data.schedule?.unavailable;
  return{market,backend,analysis,aligned,scheduleMissing,label:scheduleMissing?'校正排程缺失':(aligned?'日期已對齊':'日期待同步'),className:aligned?'ok':'warn'}
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
  return`<article class="admin-job"><div class="head"><div><b>${esc(adminJobLabel(job.jobKey))}</b><div class="muted">${esc(adminGroupLabel(job.group))} · 資料週期 ${esc(job.cycleDate||'—')} · 游標 ${fmt(job.cursor??0,0)}</div></div><span class="tag ${state.className}">${esc(state.label)}</span></div><div class="health-progress-label"><span>${fmt(job.processed??0,0)}／${fmt(job.total??0,0)}</span><b>${fmt(progress,1)}%</b></div><div class="progress"><span style="width:${progress}%"></span></div><div class="admin-job-times"><span>本次完成 ${adminTime(job.lastSuccessAt)}</span><span>預計再檢查 ${adminTime(job.nextRunAt)}</span></div>${job.lastErrorPreview?`<div class="admin-error"><b>${esc(job.lastErrorCode||'sync_error')}</b><span>${esc(job.lastErrorPreview)}</span></div>`:''}${details?`<details class="admin-details"><summary>查看工作摘要</summary><pre>${details}</pre></details>`:''}</article>`
}
function adminTimelineHtml(event){
  const labels={sync_job:'同步工作',analysis_error:'分析錯誤',repair_pending:'等待修復',api_quota:'API 額度',ranking_cycle:'排行榜週期'},state=adminStatus(event.status);
  return`<div class="admin-event"><time>${adminTime(event.at)}</time><div><b>${esc(labels[event.type]||event.type||'事件')} · ${esc(event.key||'—')}</b><span>${esc(adminGroupLabel(event.group))}${event.units!=null?` · ${fmt(event.units,0)} 次`:''}${event.errorKind?` · ${esc(event.errorKind)}`:''}</span></div>${event.status?`<span class="tag ${state.className}">${esc(state.label)}</span>`:''}</div>`
}
function adminPage(){
  if(!S.isAdmin)return'<div class="card error-card"><h2>沒有管理員權限</h2><p class="muted">請使用已授權的管理員帳號登入。</p></div>';
  if(S.adminState==='loading'&&!S.adminLog)return'<div class="card empty"><div class="loading"><span class="spinner"></span>正在讀取管理員日誌…</div></div>';
  if(S.adminState==='error'&&!S.adminLog)return`<div class="card error-card"><h2>管理日誌暫時無法取得</h2><p class="muted">${esc(S.adminError||'請稍後再試。')}</p><button id="refreshAdminLog" class="btn">重新讀取</button></div>`;
  const data=S.adminLog||{},summary=data.summary||{},health=data.health||{},jobs=Array.isArray(data.jobs)?data.jobs:[],sources=objectRows(health.sources),groups=objectRows(health.groups),repairs=Array.isArray(data.repairQueue?.items)?data.repairQueue.items:[],missing=Array.isArray(data.missingData?.examples)?data.missingData.examples:[],timeline=Array.isArray(data.timeline)?data.timeline:[],quota=data.apiQuota||{},dates=adminDateSummary(data);
  return`<div class="admin-hero"><div><small>ADMIN ONLY</small><h2>管理員後台日誌</h2><p>資料健康、同步工作、修復佇列與 API 使用狀態。此頁只保存在目前登入階段，不會寫入快取。</p></div><button id="refreshAdminLog" class="btn secondary" ${S.adminState==='loading'?'disabled':''}>${S.adminState==='loading'?'更新中…':'重新整理'}</button></div>
    <div class="admin-session"><span class="tag">管理員 ${esc(data.admin?.username||'已驗證')}</span><span>產生時間 ${adminTime(data.generatedAt)}</span></div>
    <section class="card admin-date-card ${dates.aligned?'accent':'warn-card'}"><div class="head"><div><h3>日期一致性</h3><div class="muted">市場行情、後台全市場同步與三組分析完成日分開顯示</div></div><span class="status-pill ${dates.className}">${dates.label}</span></div><div class="grid admin-date-grid">${metric('上市行情日',esc(dates.market.listed||'—'))}${metric('上櫃行情日',esc(dates.market.otc||'—'))}${metric('後台全市場日',esc(dates.backend||'—'))}${metric('三組共同分析日',esc(dates.analysis||'尚未完成'))}</div>${dates.aligned?'':`<div class="admin-date-warning">${dates.scheduleMissing?'晚間日期校正排程未安裝或已停用，請立即修復排程。':'官方行情已換日，但後台持久化週期尚未完成同日校正；晚間校正排程會再次同步。'}</div>`}</section>
    <div class="stat-strip admin-stats">${metric('待修復',fmt(summary.pendingRepairs??0,0))}${metric('分析錯誤',fmt(summary.analysisErrors??0,0))}${metric('失敗工作',fmt(summary.failedJobs??0,0))}${metric('執行中',fmt(summary.runningJobs??0,0))}${metric('完成分析',fmt(summary.readyAnalyses??0,0))}${metric('後台全市場日',esc(dates.backend||'—'))}</div>
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
    const [log,schedule]=await Promise.all([
      sb('/rest/v1/rpc/twss_admin_operations_log',{method:'POST',body:{p_limit:60}}),
      sb('/rest/v1/rpc/twss_admin_schedule_status',{method:'POST',body:{}}).catch(()=>({ready:false,unavailable:true}))
    ]);
    S.adminLog={...log,schedule};S.adminState='ready'
  }catch(error){
    S.adminLog=null;
    if(error.status===401||error.status===403||error.code==='42501'||/admin_required/i.test(error.message||'')){clearAdminState();updateAccountUi()}
    else{S.adminState='error';S.adminError='管理資料暫時無法取得，請稍後再試。'}
  }
  render()
}
*/
function navigateToTab(tab){if(!['home','opportunities','mine'].includes(tab))return;S.tab=tab;render();resetPageScroll()}

function render(){
  if(S.tab==='admin')S.tab='home';
  qa('.bottom-nav button').forEach(button=>{const active=button.dataset.tab===S.tab;button.classList.toggle('active',active);if(active)button.setAttribute('aria-current','page');else button.removeAttribute('aria-current')});
  updateAccountUi();updateMarketHeader();
  if(S.loading&&!S.stocks.length){app.innerHTML='<div class="card empty"><div class="loading"><span class="spinner"></span>正在載入官方盤後資料…</div></div>';bind();return}
  app.innerHTML=S.tab==='home'?homePage():S.tab==='opportunities'?opportunitiesPage():minePage();bind()
}

function bind(){
  qa('.bottom-nav button').forEach(button=>button.onclick=()=>navigateToTab(button.dataset.tab));
  qa('[data-detail]').forEach(element=>element.onclick=event=>{if(!event.target.closest('button'))openDetail(element.dataset.detail)});
  qa('[data-analysis]').forEach(element=>element.onclick=event=>{event.stopPropagation();openDetail(element.dataset.analysis)});
  qa('[data-watch]').forEach(button=>button.onclick=event=>{event.stopPropagation();toggleWatch(button.dataset.watch)});
}

function bindModal(){
  q('.modal',modalRoot)?.addEventListener('click',e=>{if(e.target.classList.contains('modal'))closeModal()});
  qa('[data-watch]',modalRoot).forEach(button=>button.onclick=e=>{e.stopPropagation();toggleWatch(button.dataset.watch)});
}

function openAccountModal(){
  if(S.session){const roleLabel=!S.adminRoleChecked?'正在確認帳戶權限…':S.isAdmin?'已驗證為管理員':'一般使用者';modalRoot.innerHTML=`<div class="modal"><div class="sheet"><button class="sheet-close">×</button><h2>雲端帳戶</h2><div class="card"><div class="head"><div><b>${esc(S.session.user?.email||'已登入')}</b><div class="muted">${roleLabel}</div></div>${S.isAdmin?'<span class="tag">管理員</span>':''}</div><p class="muted">自選清單與重要提醒會同步至 CORE 資料庫。</p>${S.isAdmin?'<button id="openAdminConsole" class="btn admin-open" type="button">開啟管理員後台</button>':''}<div class="row"><button id="syncCloud" class="btn secondary grow">立即同步</button><button id="logout" class="btn danger">登出</button></div></div><div class="muted">${esc(S.syncState)}</div></div></div>`;bindModal();q('#openAdminConsole',modalRoot)?.addEventListener('click',()=>location.assign('/admin'));q('#syncCloud',modalRoot).onclick=cloudPull;q('#logout',modalRoot).onclick=logoutAccount;return}
  modalRoot.innerHTML=`<div class="modal"><div class="sheet"><button class="sheet-close">×</button><h2>登入台股智選</h2><p class="muted">登入後可同步自選清單與重要提醒。</p><label>電子郵件<input id="authEmail" type="email" autocomplete="email"></label><label>密碼<input id="authPass" type="password" autocomplete="current-password" placeholder="至少 6 個字元"></label><div class="row" style="margin-top:12px"><button id="loginBtn" class="btn grow">登入</button><button id="signupBtn" class="btn secondary">建立帳戶</button></div><div id="authMsg" class="muted" style="margin-top:10px"></div></div></div>`;bindModal();
  const afterAuth=()=>{closeModal();render()};
  const act=async type=>{const email=q('#authEmail',modalRoot).value.trim(),password=q('#authPass',modalRoot).value,msg=q('#authMsg',modalRoot);if(!email||password.length<6){msg.textContent='請輸入有效電子郵件，密碼至少 6 個字元。';return}msg.textContent='處理中…';try{if(type==='login'){await login(email,password);afterAuth()}else{const ok=await signup(email,password);if(ok)afterAuth();else msg.textContent='驗證信已寄出，完成驗證後再登入。'}}catch(e){msg.textContent=e.message}};
  q('#loginBtn',modalRoot).onclick=()=>act('login');q('#signupBtn',modalRoot).onclick=()=>act('signup')
}

document.querySelector('#accountBtn').onclick=openAccountModal;
if('serviceWorker'in navigator)navigator.serviceWorker.register('/sw.js?v=20.2.0',{updateViaCache:'none'}).catch(()=>{});
initSession();render();
if(document.querySelector('script[src^="/v20.js"]'))S.fundStatus='deferred';
else loadStocks();
