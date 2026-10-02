// ─── State ───────────────────────────────────────────────────────────────────
const state = {
  rideId:      null,   // single source of truth for the active ride ID
  rideStatus:  '',
  completedFare: 0,
  driver:      null,
  pollInterval: null,
};

let rideSocket         = null;
let notificationSocket = null;
let audioEnabled       = false;
let notificationSound  = null;

// ─── Utilities ───────────────────────────────────────────────────────────────

function getCookie(name) {
  return document.cookie.split(';').reduce((val, part) => {
    const [k, v] = part.trim().split('=');
    return k === name ? decodeURIComponent(v) : val;
  }, null);
}

function el(id) { return document.getElementById(id); }

function show(id) { const e = el(id); if (e) e.style.display = 'block'; }
function hide(id) { const e = el(id); if (e) e.style.display = 'none'; }

function showToast(type, title, body, duration = 5000) {
  document.querySelectorAll('.app-toast').forEach(t => t.remove());
  const icons = { success: 'fa-check-circle', error: 'fa-exclamation-circle' };
  const toast = document.createElement('div');
  toast.className = `app-toast app-toast--${type}`;
  toast.innerHTML = `
    <div class="toast-content">
      <i class="fas ${icons[type] || icons.error}"></i>
      <div class="toast-text"><strong>${title}</strong><span>${body}</span></div>
      <button class="toast-close">&times;</button>
    </div>`;
  document.body.appendChild(toast);
  toast.querySelector('.toast-close').onclick = () => toast.remove();
  setTimeout(() => toast?.parentNode && toast.remove(), duration);
}

async function postJSON(url, body) {
  const res = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': getCookie('csrftoken'),
      'X-Requested-With': 'XMLHttpRequest',
    },
    body: JSON.stringify(body),
    credentials: 'same-origin',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || err.message || `HTTP ${res.status}`);
  }
  return res.json();
}

// ─── Audio ───────────────────────────────────────────────────────────────────

function initAudio() {
  notificationSound = new Audio('/static/assets/new-notification-3-398649.mp3');
  notificationSound.volume = 0.7;
  notificationSound.preload = 'auto';
  ['click', 'keydown', 'touchstart'].forEach(ev =>
    document.addEventListener(ev, () => { audioEnabled = true; }, { once: true })
  );
}

function playSound() {
  if (!audioEnabled || !notificationSound) return;
  notificationSound.currentTime = 0;
  notificationSound.play().catch(() => {});
}

// ─── Session init ─────────────────────────────────────────────────────────────

function initFromSession() {
  const data = el('ride-data');
  if (!data) return;

  state.rideId       = data.dataset.currentRideId || null;
  state.rideStatus   = data.dataset.currentRideStatus || '';
  state.completedFare = parseFloat(data.dataset.completedFare) || 0;

  try {
    const d = data.dataset.currentDriver;
    state.driver = (d && d !== 'null') ? JSON.parse(d) : null;
  } catch { state.driver = null; }
}

// ─── WebSocket ────────────────────────────────────────────────────────────────

function wsConnect(url, onMessage, onReconnect) {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const ws = new WebSocket(`${proto}//${location.host}${url}`);
  ws.onmessage = e => onMessage(JSON.parse(e.data));
  ws.onclose   = () => setTimeout(() => onReconnect(), 3000);
  ws.onerror   = e => console.error(`WS error ${url}`, e);
  return ws;
}

function connectRideSocket() {
  rideSocket = wsConnect('/ws/ride/updates/', handleRideMessage, connectRideSocket);
  rideSocket.onopen = () => {
    if (state.rideId) subscribeToRide(state.rideId);
  };
}

function connectNotificationSocket() {
  notificationSocket = wsConnect(
    '/ws/notifications/',
    data => { if (data.type === 'counter') updateNotificationBadge(data.count); },
    connectNotificationSocket,
  );
}

function subscribeToRide(rideId) {
  if (rideSocket?.readyState === WebSocket.OPEN) {
    rideSocket.send(JSON.stringify({ action: 'subscribe', ride_id: rideId }));
  }
}

function handleRideMessage(data) {
  if (data.type !== 'ride_update') return;
  if (data.event === 'accepted') playSound();
  updateTrackingUI({
    status: data.event,
    driver: data.data?.driver,
    eta:    data.data?.eta,
    fare:   data.data?.fare,
  });
}

// ─── Polling (fallback alongside WS) ─────────────────────────────────────────

function startPolling() {
  stopPolling();
  checkStatus();
  state.pollInterval = setInterval(checkStatus, 5000);
}

function stopPolling() {
  clearInterval(state.pollInterval);
  state.pollInterval = null;
}

async function checkStatus() {
  if (!state.rideId) return;
  try {
    const res = await fetch(`/ride-status/${state.rideId}/`);
    if (!res.ok) return;
    const data = await res.json();
    updateTrackingUI(data);
    if (['completed', 'cancelled'].includes(data.status)) stopPolling();
  } catch { /* network blip — poll will retry */ }
}

// ─── Notification badge ───────────────────────────────────────────────────────

function updateNotificationBadge(count) {
  const badge = document.querySelector('.menu-badge');
  if (!badge) return;
  badge.textContent = count;
  badge.style.display = count > 0 ? 'inline-block' : 'none';
}

// ─── Google Maps autocomplete ─────────────────────────────────────────────────

window.initAutocomplete = function () {
  if (!window.google?.maps?.places) return;
  const opts = {
    types: ['address'],
    fields: ['formatted_address', 'geometry', 'place_id'],
    componentRestrictions: { country: 'ng' },
    locationBias: { radius: 30000, center: { lat: 6.3350, lng: 5.6037 } },
  };
  ['current-location', 'destination'].forEach(id => {
    const input = el(id);
    if (input) new google.maps.places.Autocomplete(input, opts);
  });
};

function loadGoogleMaps() {
  if (window.google?.maps?.places) { initAutocomplete(); return; }
  if (document.querySelector('script[src*="maps.googleapis.com"]')) return;

  const apiKey = el('ride-data')?.dataset?.googleMapsApiKey;
  if (!apiKey) { showFallbackInputs(); return; }

  const script = document.createElement('script');
  script.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(apiKey)}&libraries=places&callback=initAutocomplete`;
  script.async = script.defer = true;
  script.onerror = showFallbackInputs;
  document.head.appendChild(script);
}

function showFallbackInputs() {
  const c = document.querySelector('.location-inputs');
  if (c) c.innerHTML = `
    <input type="text" id="current-location" placeholder="Enter pickup location" class="fallback-input">
    <input type="text" id="destination"       placeholder="Enter destination"     class="fallback-input">`;
}

// ─── Fare calculation ─────────────────────────────────────────────────────────

async function calculateFare() {
  const pickup      = el('current-location')?.value?.trim();
  const destination = el('destination')?.value?.trim();
  if (!pickup || !destination) { hide('fareEstimate'); return; }

  const btn = document.querySelector('.submit-btn');
  if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Calculating...'; }

  try {
    const data = await postJSON('/api/estimate-fare/', {
      pickup, destination, vehicle_type: 'standard',
    });

    const fmt = new Intl.NumberFormat('en-NG', { style: 'currency', currency: 'NGN', minimumFractionDigits: 2 });
    el('fareAmount').textContent    = fmt.format(data.total_fare);
    el('distanceText').textContent  = `${parseFloat(data.distance_km).toFixed(1)} km`;
    el('durationText').textContent  = `${Math.round(data.duration_min)} mins`;

    const surge = parseFloat(data.surge_multiplier) || 1;
    const surgeEl = el('surgeNotice');
    if (surgeEl) surgeEl.style.display = surge > 1 ? 'block' : 'none';
    if (surge > 1 && el('surgeMultiplier')) el('surgeMultiplier').textContent = surge.toFixed(1);

    show('fareEstimate');
  } catch (err) {
    hide('fareEstimate');
    showToast('error', 'Fare Error', err.message || 'Failed to calculate fare');
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fas fa-paper-plane"></i> Request Delivery'; }
  }
}

// ─── Booking ──────────────────────────────────────────────────────────────────

async function bookRide(pickup, destination) {
  const btn = document.querySelector('.submit-btn');
  if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Booking...'; }

  try {
    const data = await postJSON('/request_ride/', { current_location: pickup, destination });
    state.rideId = data.ride_id;
    showTrackingCard();
    subscribeToRide(data.ride_id);
    startPolling();
  } catch (err) {
    showToast('error', 'Booking Failed', err.message.includes('fetch') ? 'Network error — check your connection.' : err.message);
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fas fa-paper-plane"></i> Request Delivery'; }
  }
}

// ─── Tracking card show/hide ──────────────────────────────────────────────────

function showTrackingCard() {
  hide('rideForm');
  show('rideTrackingCard');
  // Reset all sub-states
  ['searchingState','driverAssignedState','tripCompletedState','payNowBtn','paymentCompletedState']
    .forEach(hide);
  show('searchingState');
  show('cancelRideBtn');
}

function showBookingForm() {
  show('rideForm');
  hide('rideTrackingCard');
  el('current-location') && (el('current-location').value = '');
  el('destination')      && (el('destination').value = '');
  hide('fareEstimate');
  state.rideId = null;
}

// ─── Tracking UI updates ──────────────────────────────────────────────────────

function updateTrackingUI(data) {
  const statusEl = el('trackingStatus');
  if (!statusEl) return;

  // Hide all states first
  ['searchingState','driverAssignedState','tripCompletedState','payNowBtn','paymentCompletedState']
    .forEach(hide);

  switch (data.status) {
    case 'pending':
      statusEl.textContent = 'Finding you a Dispatch Rider';
      show('searchingState');
      show('cancelRideBtn');
      break;

    case 'accepted':
      statusEl.textContent = 'Dispatch Rider is on the way!';
      show('driverAssignedState');
      show('cancelRideBtn');
      _renderDriverInfo(data.driver || state.driver);
      const etaEl = el('estimatedArrival');
      if (etaEl) etaEl.textContent = data.eta ? `ETA: ${data.eta} min` : 'Calculating...';
      break;

    case 'started':
      statusEl.textContent = 'Dispatch in progress';
      show('driverAssignedState');
      hide('cancelRideBtn');
      const routeEl = el('estimatedArrival');
      if (routeEl) routeEl.textContent = 'En route to destination';
      break;

    case 'completed': {
      statusEl.textContent = 'Dispatch Complete';
      show('tripCompletedState');
      hide('cancelRideBtn');

      const fare = data.fare || state.completedFare || 0;
      el('completedFareAmount') && (el('completedFareAmount').textContent = fare.toFixed(2));
      el('payNowAmount')        && (el('payNowAmount').textContent        = fare.toFixed(2));

      const driver = data.driver || state.driver;
      if (driver) {
        el('completedDriverName')  && (el('completedDriverName').textContent  = driver.name || 'Driver');
        el('completedVehicleInfo') && (el('completedVehicleInfo').textContent =
          driver.car_model && driver.license_plate
            ? `${driver.car_model} • ${driver.license_plate}`
            : 'Vehicle info');
      }

      if (data.payment_status === 'paid') {
        show('paymentCompletedState');
      } else {
        const payBtn = el('payNowBtn');
        if (payBtn) {
          payBtn.dataset.rideId = state.rideId;
          payBtn.dataset.amount = fare;
          show('payNowBtn');
        }
      }
      break;
    }

    case 'cancelled':
      statusEl.textContent = 'Dispatch cancelled';
      statusEl.style.color = 'red';
      hide('cancelRideBtn');
      setTimeout(showBookingForm, 3000);
      break;
  }
}

function _renderDriverInfo(driver) {
  if (!driver) return;
  el('driverName')  && (el('driverName').textContent  = driver.name || 'Rider assigned');
  el('vehicleInfo') && (el('vehicleInfo').textContent =
    driver.car_model && driver.license_plate
      ? `${driver.car_model} • ${driver.license_plate}`
      : 'Vehicle details coming soon');

  const phoneEl = el('driverPhone');
  if (phoneEl) {
    phoneEl.innerHTML = driver.phone && driver.phone !== 'Not available'
      ? `<a href="tel:${driver.phone}" style="color:#007bff">${driver.phone}</a>`
      : 'Not available';
  }
  _renderStars(driver.rating || 4.5);
}

function _renderStars(rating) {
  const el_ = document.querySelector('.driver-rating');
  if (!el_) return;
  const full = Math.floor(rating);
  const half = rating % 1 >= 0.5;
  el_.innerHTML = Array.from({ length: 5 }, (_, i) =>
    `<i class="fa${i < full ? 's' : (i === full && half ? 's fa-star-half-alt' : 'r')} fa-star"></i>`
  ).join('');
}

// ─── Cancel ride ──────────────────────────────────────────────────────────────

async function cancelRide() {
  if (!state.rideId || !confirm('Are you sure you want to cancel this ride?')) return;
  const btn = el('cancelRideBtn');
  if (btn) btn.disabled = true;
  try {
    await postJSON(`/cancel-ride/${state.rideId}/`, {});
    stopPolling();
    if (rideSocket?.readyState === WebSocket.OPEN) {
      rideSocket.send(JSON.stringify({ action: 'unsubscribe', ride_id: state.rideId }));
    }
    showBookingForm();
  } catch (err) {
    showToast('error', 'Cancel Failed', err.message);
  } finally {
    if (btn) btn.disabled = false;
  }
}

// ─── Payment ──────────────────────────────────────────────────────────────────

async function initiatePayment(rideId) {
  try {
    const data = await postJSON(`/initiate-payment/${rideId}/`, {});
    if (data.payment_url) { window.location.href = data.payment_url; return; }
    throw new Error(data.error || 'No payment URL returned');
  } catch (err) {
    showToast('error', 'Payment Failed', err.message);
    hide('paymentProcessingBtn');
    show('payNowBtn');
  }
}

function handlePaymentRedirect() {
  const params = new URLSearchParams(location.search);
  const status = params.get('payment');
  const amount = params.get('amount');
  if (!status) return;

  history.replaceState({}, '', location.pathname);

  if (status === 'success') {
    showToast('success', 'Payment Successful!', `₦${parseFloat(amount).toFixed(2)} paid`);
    fetch('/rider/completed-rides/', { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
      .then(r => r.json())
      .then(d => { const c = el('completedRidesContainer'); if (c) c.innerHTML = d.html; })
      .catch(() => {});
  } else if (status === 'failed') {
    showToast('error', 'Payment Failed', 'Please try again or contact support');
  }
}

// ─── Session restore ──────────────────────────────────────────────────────────

function restoreFromSession() {
  if (!state.rideId) { showBookingForm(); return; }

  showTrackingCard();
  updateTrackingUI({ status: state.rideStatus, fare: state.completedFare, driver: state.driver,
    payment_status: state.rideStatus === 'completed' ? 'pending' : null });

  subscribeToRide(state.rideId);

  if (state.rideId === 'accepted') playSound();
  if (state.rideStatus !== 'completed') startPolling();
  else checkStatus();
}

// ─── Bootstrap ───────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  initAudio();
  initFromSession();
  loadGoogleMaps();
  connectRideSocket();
  connectNotificationSocket();
  handlePaymentRedirect();

  // Restore or show form after sockets have a moment to open
  setTimeout(restoreFromSession, 400);

  // Form submit: calculate fare first, then book on second submit
  el('rideForm')?.addEventListener('submit', e => {
    e.preventDefault();
    const pickup      = el('current-location')?.value?.trim();
    const destination = el('destination')?.value?.trim();
    if (!pickup || !destination) { alert('Please enter both locations'); return; }
    el('fareEstimate')?.style.display === 'block'
      ? bookRide(pickup, destination)
      : calculateFare();
  });

  el('cancelRideBtn')?.addEventListener('click', cancelRide);

  // Pay button — event delegation so it works even when button is hidden/shown
  el('payNowBtn')?.addEventListener('click', function () {
    hide('payNowBtn');
    show('paymentProcessingBtn');
    initiatePayment(this.dataset.rideId);
  });
});