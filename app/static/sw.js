const CACHE_VERSION = 'telentregas-v7';

self.addEventListener('install', event => event.waitUntil(
  caches.open(CACHE_VERSION).then(cache => cache.addAll(['/motoboy/', '/static/css/app.css'])).then(() => self.skipWaiting())
));
self.addEventListener('activate', event => event.waitUntil(
  caches.keys().then(keys => Promise.all(keys.filter(key => key !== CACHE_VERSION).map(key => caches.delete(key))))
    .then(() => self.clients.claim())
));
self.addEventListener('push', event => {
  const data = event.data ? event.data.json() : {};
  event.waitUntil(self.registration.showNotification(data.title || 'Nova entrega!', {
    body: data.body || 'Há uma nova corrida disponível.',
    icon: '/static/icons/icon-192.png',
    badge: '/static/icons/icon-192.png',
    data: {url: data.url || '/motoboy/'}
  }));
});
self.addEventListener('notificationclick', event => {
  event.notification.close();
  event.waitUntil(clients.openWindow(event.notification.data.url || '/motoboy/'));
});
