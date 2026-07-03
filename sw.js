// Self-destructing service worker.
// An earlier version of this file cached /index.html on install and served it
// cache-first forever, freezing the homepage at the install date (June 5) for
// returning visitors. Browsers re-check this file on navigation, so this
// replacement deletes every cache, unregisters itself, and reloads open tabs.
self.addEventListener('install', function (event) {
  self.skipWaiting();
});

self.addEventListener('activate', function (event) {
  event.waitUntil(
    caches.keys()
      .then(function (keys) {
        return Promise.all(keys.map(function (key) { return caches.delete(key); }));
      })
      .then(function () { return self.registration.unregister(); })
      .then(function () { return self.clients.matchAll({ type: 'window' }); })
      .then(function (clients) {
        clients.forEach(function (client) { client.navigate(client.url); });
      })
  );
});
// No fetch handler: all requests go straight to the network.
