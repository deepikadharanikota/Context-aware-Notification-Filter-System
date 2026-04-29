const CACHE_NAME = 'neuralnotify-bridge-v1';
const OFFLINE_URLS = [
  '/android-app/',
  '/android-app/index.html',
  '/android-app/manifest.json',
];

// Install: cache shell resources
self.addEventListener('install', event => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(OFFLINE_URLS))
  );
});

// Activate: clean up old caches
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// Fetch: network-first for API calls, cache-first for app shell
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);

  // Always go network for API endpoints
  if (url.pathname.startsWith('/push') ||
      url.pathname.startsWith('/device') ||
      url.pathname.startsWith('/ws')) {
    return;
  }

  event.respondWith(
    fetch(event.request)
      .then(response => {
        // Cache successful app shell responses
        if (response.ok && OFFLINE_URLS.includes(url.pathname)) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
        }
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});

// Background sync: retry failed notification POSTs
self.addEventListener('sync', event => {
  if (event.tag === 'retry-push') {
    event.waitUntil(retryFailedPushes());
  }
});

async function retryFailedPushes() {
  // Retrieve pending pushes from IndexedDB (set by the main app)
  // This is a stub — the companion app stores failures in localStorage
  // and replays them next time it goes online
  const clients = await self.clients.matchAll();
  clients.forEach(c => c.postMessage({ type: 'sw_online', retrying: true }));
}

// Push notification display (if server sends Web Push)
self.addEventListener('push', event => {
  const data = event.data ? event.data.json() : {};
  event.waitUntil(
    self.registration.showNotification(data.title || 'NeuralNotify', {
      body: data.body || '',
      icon: '/android-app/icon-192.png',
      badge: '/android-app/icon-192.png',
      tag: 'neuralnotify',
      data: data,
    })
  );
});
