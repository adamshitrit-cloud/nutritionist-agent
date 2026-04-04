self.addEventListener('install', e => e.waitUntil(caches.open('nutriai-v1').then(c => c.addAll(['/app', '/static/manifest.json']))));
self.addEventListener('fetch', e => e.respondWith(fetch(e.request).catch(() => caches.match(e.request))));
