const CACHE_NAME = 'gocab-static-v2';
const staticAssets = [
  '/static/assets/css/signin.css',
  '/static/assets/css/get-a-ride.css',
  '/static/assets/css/become-a-driver.css',
  '/static/assets/css/driver-dashboard.css',
  '/static/assets/css/driver-profile.css',
  '/static/assets/css/rider-dashboard.css',
  '/static/assets/css/main.css',
  '/static/manifest.json'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(staticAssets))
  );
});

self.addEventListener('fetch', (event) => {
  
  if (event.request.url.includes('/static/')) {
    event.respondWith(
      caches.match(event.request)
        .then((response) => response || fetch(event.request))
    );
  }
 
});