const CACHE='twss-v20.1.3';
const HOME_SNAPSHOT_PATH='/api/v20/home';
const HOME_SNAPSHOT_URL=new URL(HOME_SNAPSHOT_PATH,self.location.origin).href;
const STATIC=[
  '/',
  '/app.js?v=20.1.3',
  '/patch.js?v=20.1.3',
  '/smart.js?v=20.1.3',
  '/v20.js?v=20.1.3',
  '/styles.css?v=20.1.3',
  '/manifest.webmanifest?v=20.1.3',
  '/icon.svg?v=20.1.3'
];

async function putSuccessful(cache,key,response){
  if(response.ok){await cache.put(key,response.clone())}
  return response
}

async function installSnapshot(){
  const cache=await caches.open(CACHE);
  await Promise.allSettled(STATIC.map(async path=>{
    const response=await fetch(path,{cache:'reload'});
    await putSuccessful(cache,path,response)
  }));
  await Promise.allSettled([
    fetch(HOME_SNAPSHOT_URL,{cache:'no-store',headers:{accept:'application/json'}})
      .then(response=>putSuccessful(cache,HOME_SNAPSHOT_URL,response))
  ]);
  await self.skipWaiting()
}

self.addEventListener('install',event=>event.waitUntil(installSnapshot()));

self.addEventListener('activate',event=>event.waitUntil(
  caches.keys()
    .then(keys=>Promise.all(keys.filter(key=>key!==CACHE).map(key=>caches.delete(key))))
    .then(()=>self.clients.claim())
));

self.addEventListener('fetch',event=>{
  if(event.request.method!=='GET')return;
  const url=new URL(event.request.url);
  if(url.origin!==location.origin)return;
  if(url.pathname===HOME_SNAPSHOT_PATH){
    event.respondWith(
      caches.open(CACHE).then(async cache=>{
        const cached=await cache.match(HOME_SNAPSHOT_URL);
        const refresh=fetch(event.request,{cache:'no-store'}).then(response=>
          putSuccessful(cache,HOME_SNAPSHOT_URL,response)
        );
        if(cached){event.waitUntil(refresh.catch(()=>{}));return cached}
        return refresh.catch(async error=>{
          const fallback=await cache.match(HOME_SNAPSHOT_URL);
          if(fallback)return fallback;
          throw error
        })
      })
    );
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
    event.respondWith(
      fetch(event.request,{cache:'no-store'})
        .then(response=>{
          if(response.ok){const copy=response.clone();caches.open(CACHE).then(cache=>cache.put('/',copy))}
          return response;
        })
        .catch(()=>caches.match('/'))
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
