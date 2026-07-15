const CACHE='twss-v19.1.0';
const STATIC=[
  '/',
  '/app.js?v=19.1.0',
  '/patch.js?v=19.1.0',
  '/smart.js?v=19.1.0',
  '/styles.css?v=19.1.0',
  '/manifest.webmanifest?v=19.1.0',
  '/icon.svg?v=19.1.0'
];

self.addEventListener('install',event=>event.waitUntil(
  caches.open(CACHE).then(cache=>cache.addAll(STATIC)).then(()=>self.skipWaiting())
));

self.addEventListener('activate',event=>event.waitUntil(
  caches.keys()
    .then(keys=>Promise.all(keys.filter(key=>key!==CACHE).map(key=>caches.delete(key))))
    .then(()=>self.clients.claim())
));

self.addEventListener('fetch',event=>{
  if(event.request.method!=='GET')return;
  const url=new URL(event.request.url);
  if(url.origin!==location.origin)return;
  if(url.pathname.startsWith('/api/')){
    event.respondWith(fetch(event.request));
    return;
  }
  if(url.pathname.startsWith('/data/')){
    const cacheKey=new Request(url.origin+url.pathname);
    event.respondWith(
      fetch(event.request,{cache:'no-store'})
        .then(response=>{
          if(!response.ok)return response;
          const copy=response.clone();
          caches.open(CACHE).then(cache=>cache.put(cacheKey,copy));
          return response;
        })
        .catch(()=>caches.match(cacheKey))
    );
    return;
  }
  if(event.request.mode==='navigate'){
    event.respondWith(
      fetch(event.request,{cache:'no-store'})
        .then(response=>{
          const copy=response.clone();
          caches.open(CACHE).then(cache=>cache.put('/',copy));
          return response;
        })
        .catch(()=>caches.match('/'))
    );
    return;
  }
  event.respondWith(
    caches.match(event.request)
      .then(cached=>cached||fetch(event.request).then(response=>{
        const copy=response.clone();
        caches.open(CACHE).then(cache=>cache.put(event.request,copy));
        return response;
      }))
  );
});
