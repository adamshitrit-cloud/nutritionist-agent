self.addEventListener('install', e => e.waitUntil(caches.open('nutriai-v1').then(c => c.addAll(['/app', '/static/manifest.json']))));
self.addEventListener('fetch', e => e.respondWith(fetch(e.request).catch(() => caches.match(e.request))));
self.addEventListener('push', e => {
  const data = e.data ? e.data.json() : {title:'NutriAI', body:'תזכורת!'};
  e.waitUntil(self.registration.showNotification(data.title, {
    body: data.body,
    icon: '/static/icon-192.png',
    badge: '/static/icon-192.png',
    dir: 'rtl',
    lang: 'he'
  }));
});
self.addEventListener('notificationclick', e => {
  e.notification.close();
  e.waitUntil(clients.openWindow('/app'));
});
