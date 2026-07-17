const CACHE='twss-v20.2.1';
const HOME_SNAPSHOT_PATH='/api/v20/home';
const HOME_SNAPSHOT_URL=new URL(HOME_SNAPSHOT_PATH,self.location.origin).href;
const STATIC=[
  '/',
  '/app.js?v=20.2.1',
  '/patch.js?v=20.2.1',
  '/smart.js?v=20.2.1',
  '/v20.js?v=20.2.1',
  '/styles.css?v=20.2.1',
  '/manifest.webmanifest?v=20.2.1',
  '/icon.svg?v=20.2.1'
];

async function putSuccessful(cache,key,response){
  if(response.ok){await cache.put(key,response.clone())}
  return response
}

async function homePublication(response){
  if(!response?.ok)return null;
  try{
    const payload=await response.clone().json();
    if(!payload||payload.error||payload.maintenance===true||payload.dataState==='error'||payload.status==='error')return null;
    const runId=Number(payload.runId);
    const publicationKey=String(payload.publicationKey||'');
    const contentHash=String(payload.contentHash||'');
    const dataDate=String(payload.dataDate||'').slice(0,10);
    if(!Number.isInteger(runId)||runId<=0||!/^[0-9a-f]{64}$/i.test(publicationKey)||!/^[0-9a-f]{64}$/i.test(contentHash)||!/^\d{4}-\d{2}-\d{2}$/.test(dataDate))return null;
    return {runId,publicationKey,contentHash,dataDate}
  }catch{return null}
}

function sameHomePublication(left,right){
  return left?.runId===right?.runId
    && left?.publicationKey===right?.publicationKey
    && left?.contentHash===right?.contentHash
    && left?.dataDate===right?.dataDate
}

async function notifyHomePublication(publication){
  const clients=await self.clients.matchAll({type:'window',includeUncontrolled:true});
  clients.forEach(client=>client.postMessage({type:'twss-home-publication-updated',publication}))
}

async function refreshHomeSnapshot(cache,request,cached){
  const response=await fetch(request,{cache:'no-store'});
  const nextPublication=await homePublication(response);
  if(!nextPublication){
    if(response.ok)throw new Error('invalid home snapshot');
    return response
  }
  const previousPublication=await homePublication(cached);
  await cache.put(HOME_SNAPSHOT_URL,response.clone());
  if(previousPublication&&!sameHomePublication(previousPublication,nextPublication)){
    await notifyHomePublication(nextPublication)
  }
  return response
}

async function installSnapshot(){
  const cache=await caches.open(CACHE);
  await Promise.allSettled(STATIC.map(async path=>{
    const response=await fetch(path,{cache:'reload'});
    await putSuccessful(cache,path,response)
  }));
  await Promise.allSettled([
    refreshHomeSnapshot(cache,new Request(HOME_SNAPSHOT_URL,{headers:{accept:'application/json'}}),null)
  ]);
  await self.skipWaiting()
}

self.addEventListener('install',event=>event.waitUntil(installSnapshot()));

self.addEventListener('activate',event=>event.waitUntil(
  caches.keys()
    .then(keys=>Promise.all(keys.filter(key=>key.startsWith('twss-')&&key!==CACHE).map(key=>caches.delete(key))))
    .then(()=>self.clients.claim())
));

self.addEventListener('fetch',event=>{
  if(event.request.method!=='GET')return;
  const url=new URL(event.request.url);
  if(url.origin!==location.origin)return;
  if(url.pathname===HOME_SNAPSHOT_PATH){
    let refreshPromise;
    const responsePromise=caches.open(CACHE).then(async cache=>{
      const cached=await cache.match(HOME_SNAPSHOT_URL);
      refreshPromise=refreshHomeSnapshot(cache,event.request,cached);
      if(!cached)return refreshPromise;
      const timeout=new Promise(resolve=>setTimeout(()=>resolve(cached),2000));
      const networkFirst=refreshPromise.then(response=>response.ok?response:cached).catch(()=>cached);
      return Promise.race([networkFirst,timeout])
    });
    event.respondWith(responsePromise);
    event.waitUntil(responsePromise.then(()=>refreshPromise,()=>refreshPromise).catch(()=>{}));
    return;
  }
  if(url.pathname.startsWith('/api/')){
    event.respondWith(fetch(event.request));
    return;
  }
  if(url.pathname.startsWith('/data/')){
    const cacheKey=new Request(url.origin+url.pathname);
    event.respondWith(
      caches.match(cacheKey).then(cached=>{
        const refresh=fetch(event.request,{cache:'no-store'}).then(response=>{
          if(response.ok){const copy=response.clone();caches.open(CACHE).then(cache=>cache.put(cacheKey,copy))}
          return response
        });
        if(cached){event.waitUntil(refresh.catch(()=>{}));return cached}
        return refresh.catch(()=>caches.match(cacheKey))
      })
    );
    return;
  }
  if(event.request.mode==='navigate'){
    const isAppShell=url.pathname==='/'||url.pathname==='/index.html';
    event.respondWith(
      fetch(event.request,{cache:'no-store'})
        .then(response=>{
          if(response.ok&&isAppShell){const copy=response.clone();caches.open(CACHE).then(cache=>cache.put('/',copy))}
          return response;
        })
        .catch(()=>isAppShell?caches.match('/'):Response.error())
    );
    return;
  }
  event.respondWith(
    caches.match(event.request)
      .then(cached=>cached||fetch(event.request).then(response=>{
        if(response.ok){const copy=response.clone();caches.open(CACHE).then(cache=>cache.put(event.request,copy))}
        return response;
      }))
  );
});
