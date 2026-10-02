document.addEventListener('DOMContentLoaded', function () {
  const body = document.body;
  const roleInput = document.getElementById('role-input');
  const roleButtons = document.querySelectorAll('[data-role-btn]');
  const driverOnlyFields = document.querySelectorAll(
    '[data-role-section="driver"] input, [data-role-section="driver"] select'
  );

  let locationDetected = false;
  // Already true when arriving from the homepage's single email step — it
  // hands off a verified_token instead of re-showing the code UI (see
  // signup.html's {% if not verified_token %} block).
  let codeSent = !!document.getElementById('id_verified_token');

  function setActiveRole(role) {
    body.dataset.activeRole = role;
    roleInput.value = role;
    roleButtons.forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.roleBtn === role);
    });

    // Only require driver-only fields (incl. file inputs) when driver mode
    // is active, otherwise a hidden required field blocks rider submission.
    driverOnlyFields.forEach((field) => {
      if (field.type === 'file') {
        field.required = role === 'driver';
      } else if (field.hasAttribute('data-always-optional')) {
        // no-op
      } else if (['date_of_birth', 'national_identification_number', 'vehicle_model', 'license_plate', 'bank_name', 'account_number', 'account_holder_name'].includes(field.name)) {
        field.required = role === 'driver';
      }
    });

    updateSubmitButton();
  }

  roleButtons.forEach((btn) => {
    btn.addEventListener('click', () => setActiveRole(btn.dataset.roleBtn));
  });

  // Phone number formatting (mirrors the server's normalize_phone_number)
  const phoneInput = document.getElementById('id_phone_number');
  if (phoneInput) {
    phoneInput.addEventListener('input', (e) => {
      let value = e.target.value.replace(/\D/g, '');
      if (value.startsWith('234')) {
        value = '+' + value;
      } else if (value.startsWith('0')) {
        value = '+234' + value.substring(1);
      }
      e.target.value = value;
    });
  }

  // Geolocation capture (driver only)
  const detectBtn = document.getElementById('detect-location');
  const locationStatus = document.getElementById('location-status');
  const locationDetails = document.getElementById('location-details');
  const locationAddress = document.getElementById('location-address');
  const locationCoords = document.getElementById('location-coords');
  const latitudeField = document.getElementById('id_latitude');
  const longitudeField = document.getElementById('id_longitude');
  const addressField = document.getElementById('id_current_address');
  const submitBtn = document.getElementById('submit-btn');

  function updateSubmitButton() {
    if (!submitBtn) return;
    const needsLocation = body.dataset.activeRole === 'driver' && !locationDetected;
    const needsCode = !codeSent;
    const blocked = needsLocation || needsCode;
    submitBtn.disabled = blocked;
    submitBtn.style.opacity = blocked ? '0.6' : '1';
    submitBtn.style.cursor = blocked ? 'not-allowed' : 'pointer';
    submitBtn.title = needsCode
      ? 'Please verify your email first'
      : (needsLocation ? 'Please detect your location first' : '');
  }

  function extractErrorMessage(data) {
    if (!data) return 'Something went wrong.';
    if (typeof data.detail === 'string') return data.detail;
    if (Array.isArray(data.detail)) {
      return data.detail.map((d) => d.msg).join(' ');
    }
    return 'Something went wrong.';
  }

  // Email verification (shared, rider + driver)
  const emailInput = document.getElementById('id_email');
  const sendCodeBtn = document.getElementById('send-code-btn');
  const codeStatus = document.getElementById('code-status');
  const codeFieldWrapper = document.getElementById('code-field-wrapper');
  const codeInput = document.getElementById('id_code');

  if (sendCodeBtn) {
    sendCodeBtn.addEventListener('click', async () => {
      const email = emailInput ? emailInput.value.trim() : '';
      if (!email) {
        codeStatus.textContent = 'Enter your email address first.';
        codeStatus.className = 'location-status error';
        return;
      }

      sendCodeBtn.disabled = true;
      codeStatus.textContent = 'Sending code...';
      codeStatus.className = 'location-status';

      try {
        const response = await fetch('/api/v1/auth/request-code', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email }),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(extractErrorMessage(data));

        codeStatus.textContent = data.detail;
        codeStatus.className = 'location-status success';
        codeFieldWrapper.style.display = 'block';
        if (codeInput) {
          codeInput.required = true;
          codeInput.focus();
        }
        sendCodeBtn.textContent = 'Resend Code';
        codeSent = true;
        updateSubmitButton();
      } catch (err) {
        codeStatus.textContent = err.message;
        codeStatus.className = 'location-status error';
      } finally {
        sendCodeBtn.disabled = false;
      }
    });
  }

  async function getAddressFromCoords(lat, lng) {
    try {
      const response = await fetch(
        `https://nominatim.openstreetmap.org/reverse?format=json&lat=${lat}&lon=${lng}&zoom=18&addressdetails=1`
      );
      if (response.ok) {
        const data = await response.json();
        if (data.display_name) return data.display_name;
      }
    } catch (error) {
      // fall through to the coordinate-based fallback below
    }
    return `Location at ${lat.toFixed(6)}, ${lng.toFixed(6)}`;
  }

  if (detectBtn) {
    detectBtn.addEventListener('click', function () {
      detectBtn.disabled = true;
      locationStatus.textContent = 'Detecting your location...';
      locationStatus.className = 'location-status';

      if (!navigator.geolocation) {
        locationStatus.textContent = 'Geolocation is not supported by this browser.';
        locationStatus.className = 'location-status error';
        detectBtn.disabled = false;
        return;
      }

      navigator.geolocation.getCurrentPosition(
        async function (position) {
          const lat = position.coords.latitude;
          const lng = position.coords.longitude;

          latitudeField.value = lat;
          longitudeField.value = lng;
          locationCoords.textContent = `${lat.toFixed(6)}, ${lng.toFixed(6)}`;

          const address = await getAddressFromCoords(lat, lng);
          locationAddress.textContent = address;
          addressField.value = address;

          locationStatus.textContent = 'Location detected successfully!';
          locationStatus.className = 'location-status success';
          locationDetails.style.display = 'block';
          detectBtn.disabled = false;
          locationDetected = true;
          updateSubmitButton();
        },
        function (error) {
          let errorMessage = 'Unable to detect your location. ';
          switch (error.code) {
            case error.PERMISSION_DENIED:
              errorMessage += 'Please allow location access and try again.';
              break;
            case error.POSITION_UNAVAILABLE:
              errorMessage += 'Location information is unavailable.';
              break;
            case error.TIMEOUT:
              errorMessage += 'Location request timed out.';
              break;
            default:
              errorMessage += 'An unknown error occurred.';
          }
          locationStatus.textContent = errorMessage;
          locationStatus.className = 'location-status error';
          detectBtn.disabled = false;
          updateSubmitButton();
        },
        { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 }
      );
    });
  }

  // Submit handling
  const form = document.querySelector('.signup-form');
  if (form) {
    form.addEventListener('submit', function (e) {
      if (!codeSent) {
        e.preventDefault();
        const codeSection = document.getElementById('code-field-wrapper');
        codeStatus.textContent = 'Please verify your email before submitting.';
        codeStatus.className = 'location-status error';
        if (codeSection) codeSection.scrollIntoView({ behavior: 'smooth', block: 'center' });
        return;
      }

      if (body.dataset.activeRole === 'driver' && !locationDetected) {
        e.preventDefault();
        const locationSection = document.getElementById('location-section-wrapper');
        locationStatus.textContent = 'Location detection is required. Please detect your location before submitting.';
        locationStatus.className = 'location-status error';
        if (locationSection) locationSection.scrollIntoView({ behavior: 'smooth', block: 'center' });
        return;
      }

      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = 'Creating Account...';
      }
    });
  }

  // Deferred until every element lookup above is in scope — setActiveRole()
  // calls updateSubmitButton(), which reads submitBtn/codeSent.
  setActiveRole(body.dataset.activeRole === 'driver' ? 'driver' : 'rider');
});
