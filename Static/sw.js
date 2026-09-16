const CACHE="ticktock-shell-v1";
self.addEventListener("install",e=>{self.skipWaiting();e.waitUntil(caches.open(CACHE).then(c=>c.addAll(["/login","/register"])).catch(()=>{}));});
self.addEventListener("activate",e=>e.waitUntil(self.clients.claim()));
self.addEventListener("fetch",e=>{if(e.request.method!=="GET")return;const u=new URL(e.request.url);if(u.origin!==location.origin)return;if(u.pathname.startsWith("/api/")||u.pathname.startsWith("/admin/")||u.pathname.includes("/uploads/"))return;e.respondWith(fetch(e.request).catch(()=>caches.match(e.request)));});
