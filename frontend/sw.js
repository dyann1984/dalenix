// DALENIX — Service Worker
// Permite uso offline de la app

const CACHE = 'dalenix-v1';
const FILES = [
  '/DALENIX_Mobile.html',
  '/js/dalenix-client.js',
  '/manifest.json',
  'https://fonts.googleapis.com/css2?family=Orbitron:wght@400;500;700&family=Share+Tech+Mono&family=Rajdhani:wght@300;400;500;600&display=swap',
  'https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js'
];

// Instalar y cachear
self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(c => {
      console.log('[SW] Cacheando archivos DALENIX');
      return c.addAll(FILES).catch(err => console.warn('[SW] Cache parcial:', err));
    })
  );
  self.skipWaiting();
});

// Activar y limpiar caches viejas
self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// Interceptar requests — cache first, network fallback
self.addEventListener('fetch', e => {
  // No interceptar WebSocket ni API
  if (e.request.url.includes('ws://') || e.request.url.includes('/api/')) return;

  e.respondWith(
    caches.match(e.request).then(cached => {
      if (cached) return cached;
      return fetch(e.request).then(res => {
        // Cachear respuestas exitosas
        if (res && res.status === 200 && res.type !== 'opaque') {
          const clone = res.clone();
          caches.open(CACHE).then(c => c.put(e.request, clone));
        }
        return res;
      }).catch(() => {
        // Fallback offline
        if (e.request.destination === 'document') {
          return caches.match('/DALENIX_Mobile.html');
        }
      });
    })
  );
});
