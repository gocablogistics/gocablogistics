// ── State ─────────────────────────────────────────────────────────────────────
let driverSocket      = null;
let reconnectAttempts = 0;
let audioEnabled      = false;
const MAX_RECONNECT   = 5;

// Ride IDs this driver just actioned themselves (accept/start/complete/cancel).
// Marked the instant the button is clicked, before the request even goes out,
// so a fast WS broadcast can never beat it and cause a false "taken by
// another driver" toast on our own action.
const myRecentActions = new Set();
function markMine(rideId) {
  if (!rideId) return;
  const id = String(rideId);
  myRecentActions.add(id);
  setTimeout(() => myRecentActions.delete(id), 8000);
}
function isMine(rideId) {
  return myRecentActions.has(String(rideId));
}

// ── Utilities ─────────────────────────────────────────────────────────────────

function getCsrf() {
  return (
    document.querySelector('[name=csrfmiddlewaretoken]')?.value ||
    document.cookie.split('; ').find(r => r.startsWith('csrftoken='))?.split('=')[1] || ''
  );
}

function el(id) { return document.getElementById(id); }

function toast(message, type = 'info') {
  const colours = { success: '#10b981', warning: '#f59e0b', error: '#ef4444', info: '#3b82f6' };
  const div = document.createElement('div');
  div.style.cssText = `position:fixed;top:20px;right:20px;padding:12px 18px;
    background:${colours[type]||colours.info};color:#fff;border-radius:8px;
    z-index:9999;animation:slideIn .3s ease-out;max-width:300px;`;
  div.textContent = message;
  document.body.appendChild(div);
  setTimeout(() => div.remove(), 4000);
}

function playSound() {
  if (!audioEnabled) return;
  new Audio('/static/assets/new-notification-09-352705.mp3').play().catch(() => {});
}

function updateBadge(id, count) {
  const b = el(id);
  if (!b) return;
  b.textContent = count;
  b.classList.toggle('has-items', count > 0);
}

// ── Duty status (busy / not busy) ───────────────────────────────────────────
// Derived, not pushed: a driver is "busy" purely based on whether they have
// an accepted or active ride right now. Recomputed alongside every accepted/
// active section refresh — no separate backend message needed.

function updateDutyStatus() {
  const btn  = el('dutyToggleBtn');
  const text = el('dutyStatusText');
  if (!btn || !text) return;

  const acceptedCount = document.querySelectorAll('#acceptedRidesContainer .trip-card').length;
  const activeCount   = document.querySelectorAll('#activeRidesContainer .trip-card').length;
  const busy = (acceptedCount + activeCount) > 0;

  const icon = btn.querySelector('i');

  if (busy) {
    btn.classList.remove('status-not-busy');
    btn.classList.add('status-busy');
    if (icon) icon.className = 'fa-solid fa-car-side';
    text.textContent = 'Busy (On Ride)';
  } else {
    btn.classList.remove('status-busy');
    btn.classList.add('status-not-busy');
    if (icon) icon.className = 'fa-solid fa-power-off';
    text.textContent = 'Not Busy';
  }
}

// ── "Last Completed" summary card ───────────────────────────────────────────
// Derived from the first row of the (page-1) history table — no extra endpoint needed.

function updateLastCompleted() {
  const target = el('lastCompletedContainer');
  if (!target) return;

  const firstRow = document.querySelector('#completedRidesContainer table tbody tr');

  if (!firstRow || !firstRow.dataset.rideId) {
    target.innerHTML = `
      <div class="empty-flow-state">
        <i class="fas fa-flag-checkered"></i>
        <p>No completed trips yet</p>
      </div>`;
    return;
  }

  const cells = firstRow.querySelectorAll('td');
  const [datetimeCell, customerCell, pickupCell, dropoffCell, fareCell, paymentCell] = cells;
  const customerName = customerCell?.querySelector('.customer-name')?.textContent.trim() || 'Passenger';

  target.innerHTML = `
    <div class="last-completed-card">
      <div class="lc-row">
        <span class="lc-label">Customer</span>
        <span class="lc-value">${customerName}</span>
      </div>
      <div class="lc-row">
        <span class="lc-label">Route</span>
        <span class="lc-value">${pickupCell?.textContent.trim()} &rarr; ${dropoffCell?.textContent.trim()}</span>
      </div>
      <div class="lc-row">
        <span class="lc-label">Fare</span>
        <span class="lc-value">${fareCell?.textContent.trim()}</span>
      </div>
      <div class="lc-row">
        <span class="lc-label">Completed</span>
        <span class="lc-value">${datetimeCell?.textContent.trim()}</span>
      </div>
      <div class="lc-row lc-payment">${paymentCell?.innerHTML || ''}</div>
    </div>`;
}

// ── Section refresh ───────────────────────────────────────────────────────────

const SECTIONS = {
  pending:   { url: '/driver/pending-rides/',    container: 'pendingRidesContainer',   badge: 'newRequestsBadge' },
  accepted:  { url: '/driver/accepted-rides/',   container: 'acceptedRidesContainer',  badge: 'acceptedRidesBadge' },
  active:    { url: '/driver/active-rides/',     container: 'activeRidesContainer',    badge: 'activeTripsBadge' },
  completed: { url: '/driver/completed-trips/',  container: 'completedRidesContainer', badge: null },
};

async function refreshSection(name, page = null) {
  const cfg = SECTIONS[name];
  if (!cfg) return;
  const container = el(cfg.container);
  if (!container) return;

  const url = page ? `${cfg.url}?page=${page}` : cfg.url;
  try {
    const res  = await fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } });
    const data = await res.json();
    container.innerHTML = data.html;
    if (cfg.badge) {
      updateBadge(cfg.badge, container.querySelectorAll('.trip-card').length);
    }
    // Duty status (busy/not busy) is derived from accepted + active ride
    // counts, so recompute it whenever either of those sections changes.
    if (name === 'accepted' || name === 'active') {
      updateDutyStatus();
    }
    // Keep the "Last Completed" summary card in sync with page 1 of the history table
    if (name === 'completed' && !page) {
      updateLastCompleted();
    }
  } catch (err) {
    console.error(`refreshSection(${name}) error:`, err);
  }
}

function refreshAll() {
  Object.keys(SECTIONS).forEach(s => refreshSection(s));
}

// ── WebSocket ─────────────────────────────────────────────────────────────────

function initWebSocket() {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  driverSocket = new WebSocket(`${proto}//${location.host}/ws/driver/updates/`);

  const statusDot  = document.querySelector('#connectionStatus .status-dot');
  const statusText = document.querySelector('#connectionStatus .status-text');
  const setStatus  = (connected, label) => {
    statusDot?.classList.toggle('connected', connected);
    if (statusText) statusText.textContent = label;
  };

  driverSocket.onopen = () => {
    reconnectAttempts = 0;
    setStatus(true, 'Live');
    toast('Connected — real-time updates active', 'success');
  };

  driverSocket.onerror = () => setStatus(false, 'Connection error');

  driverSocket.onclose = () => {
    setStatus(false, 'Reconnecting…');
    if (reconnectAttempts < MAX_RECONNECT) {
      const delay = Math.min(1000 * 2 ** reconnectAttempts, 30000);
      setTimeout(initWebSocket, delay);
      reconnectAttempts++;
    } else {
      toast('Connection lost — please refresh the page.', 'error');
    }
  };

  driverSocket.onmessage = e => {
    try { handleMessage(JSON.parse(e.data)); }
    catch (err) { console.error('WS parse error:', err); }
  };
}

// Single heartbeat interval, set once
setInterval(() => {
  if (driverSocket?.readyState === WebSocket.OPEN) {
    driverSocket.send(JSON.stringify({ type: 'heartbeat' }));
  }
}, 30000);

function removeCard(rideId, message) {
  const card = document.querySelector(`[data-ride-id="${rideId}"]`);
  if (!card) return false;
  card.style.transition = 'opacity .3s';
  card.style.opacity = '0';
  setTimeout(() => {
    card.remove();
    updateBadge('newRequestsBadge', document.querySelectorAll('#pendingRidesContainer .trip-card').length);
  }, 300);
  toast(message, 'warning');
  return true;
}

function handleMessage(data) {
  const type   = data.type;
  const event  = data.event;
  const rideId = data.ride_id;

  if (type === 'heartbeat_ack') return;

  switch (type) {
    case 'new_ride_request':
      playSound();
      toast('New ride request available!', 'success');
      refreshSection('pending');
      break;

    case 'ride_cancelled':
      if (!removeCard(rideId, 'Ride cancelled by passenger')) refreshSection('pending');
      refreshSection('accepted');
      refreshSection('active');
      break;

    case 'ride_accepted_by_other':
      // If this is our own accept echoing back (backend broadcasts to the
      // whole pool before removing the accepting driver), ignore it entirely —
      // our own fetch handler already updated the UI correctly.
      if (isMine(rideId)) break;
      if (!removeCard(rideId, 'Accepted by another driver')) refreshSection('pending');
      break;

    case 'ride_accepted':
      refreshSection('pending');
      refreshSection('accepted');
      if (!isMine(rideId)) toast('Ride accepted!', 'success');
      break;

    case 'ride_update':
      handleRideUpdate(event, rideId, data);
      break;
  }
}

function handleRideUpdate(event, rideId, data) {
  switch (event) {
    case 'accepted':
      refreshSection('pending');
      refreshSection('accepted');
      break;

    case 'started':
      refreshSection('accepted');
      refreshSection('active');
      break;

    case 'completed':
      refreshSection('active');
      refreshSection('completed'); // also refreshes the "Last Completed" card
      if (!isMine(rideId)) toast('Trip completed!', 'success');
      break;

    case 'driver_cancelled':
      refreshSection('pending');
      toast('A ride is now available', 'info');
      break;

    case 'ride_cancelled':
      if (!removeCard(rideId, 'Ride cancelled by passenger')) refreshSection('pending');
      refreshSection('accepted');
      refreshSection('active');
      break;
  }
}

// ── Event delegation (single listener) ───────────────────────────────────────

function initActions() {
  document.addEventListener('click', async e => {
    const btn = e.target.closest('.accept-btn, .start-btn, .complete-btn, .cancel-ride-btn, .page-link');
    if (!btn) return;
    e.preventDefault();

    // Pagination
    if (btn.classList.contains('page-link') && btn.dataset.page) {
      refreshSection(btn.dataset.action, btn.dataset.page);
      return;
    }

    const form = btn.closest('form');
    if (!form || btn.disabled) return;

    // Grab the ride id up front, before the request is sent — this lets us
    // mark it "mine" immediately so a WS broadcast that lands before the
    // HTTP response still gets suppressed correctly.
    const rideId = form.querySelector('[name="ride_id"]')?.value || btn.closest('.trip-card')?.dataset.rideId;

    const labels = {
      'accept-btn':     ['Accepting…',   'Accept Ride'],
      'start-btn':      ['Starting…',    'Start Trip'],
      'complete-btn':   ['Completing…',  'Complete Trip'],
      'cancel-ride-btn':['Cancelling…',  'Cancel'],
    };
    const cls = [...btn.classList].find(c => labels[c]);
    const [loadingLabel, resetLabel] = labels[cls] || ['…', 'Submit'];

    if (btn.classList.contains('cancel-ride-btn') && !confirm('Cancel this ride?')) return;

    markMine(rideId);

    btn.disabled = true;
    btn.innerHTML = `<i class="fas fa-spinner fa-spin"></i> ${loadingLabel}`;

    try {
      const res  = await fetch(form.action, {
        method: 'POST',
        headers: { 'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': getCsrf() },
        body: new FormData(form),
      });
      const data = await res.json();

      if (data.status === 'success') {
        toast(data.message || 'Done', 'success');

        // Optimistic UI: remove card immediately
        btn.closest('.trip-card')?.remove();

        // Don't wait on the WebSocket broadcast — refresh the sections this
        // action affects right away. This is the key fix: without this, the
        // Accepted/Active panels only update once a WS message happens to
        // arrive, which can lag or never reach the actioning driver at all.
        // WS still keeps everything else (and other drivers' views) in sync.
        const affectedSections = {
          'accept-btn':      ['pending', 'accepted'],
          'start-btn':       ['accepted', 'active'],
          'complete-btn':    ['active', 'completed'],
          'cancel-ride-btn': ['accepted', 'pending'],
        }[cls] || [];
        affectedSections.forEach(section => refreshSection(section));
      } else {
        throw new Error(data.message || data.error || 'Request failed');
      }
    } catch (err) {
      // The optimistic "mine" mark was wrong — the action actually failed
      // (e.g. someone else genuinely beat this driver to the ride). Undo it
      // so a real "accepted by another driver" broadcast for this ride still
      // gets handled normally instead of being silently swallowed.
      myRecentActions.delete(String(rideId));

      toast(err.message, 'error');
      btn.disabled = false;
      btn.innerHTML = resetLabel;
    }
  });
}

// ── Location ──────────────────────────────────────────────────────────────────

function updateLocation() {
  if (!navigator.geolocation) return;
  navigator.geolocation.getCurrentPosition(
    ({ coords }) => {
      fetch('/driver/update-driver-location/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
        body: JSON.stringify({ latitude: coords.latitude, longitude: coords.longitude }),
      })
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d?.status === 'success') refreshSection('pending'); })
      .catch(() => {});
    },
    err => console.warn('Geolocation error:', err.message),
    { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 },
  );
}

// ── Mobile sidebar (no-ops safely if this markup isn't present) ───────────────

function initSidebar() {
  const header = document.querySelector('.sidebar-header');
  const menu   = document.querySelector('.sidebar-menu');
  if (!header || !menu) return;

  const toggle = document.createElement('button');
  toggle.className = 'menu-toggle';
  toggle.innerHTML = '<i class="fas fa-bars"></i>';
  header.appendChild(toggle);

  toggle.addEventListener('click', () => {
    menu.classList.toggle('active');
    toggle.querySelector('i').className = menu.classList.contains('active') ? 'fas fa-times' : 'fas fa-bars';
  });

  document.addEventListener('click', e => {
    if (window.innerWidth < 768 && !e.target.closest('#sidebar') && menu.classList.contains('active')) {
      menu.classList.remove('active');
      toggle.querySelector('i').className = 'fas fa-bars';
    }
  });
}

// ── Bootstrap ─────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  ['click', 'keydown', 'touchstart'].forEach(ev =>
    document.addEventListener(ev, () => { audioEnabled = true; }, { once: true })
  );

  initSidebar();
  initActions();
  initWebSocket();
  refreshAll();

  updateLocation();
  setInterval(updateLocation, 30000);
});

// Expose pagination to template anchor tags if needed
window.loadPendingRides   = p => refreshSection('pending',   p);
window.loadAcceptedRides  = p => refreshSection('accepted',  p);
window.loadActiveRides    = p => refreshSection('active',    p);
window.loadCompletedRides = p => refreshSection('completed', p);