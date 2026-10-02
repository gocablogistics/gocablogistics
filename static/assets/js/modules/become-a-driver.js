document.addEventListener('DOMContentLoaded', function() {
    const detectBtn = document.getElementById('detect-location');
    const locationStatus = document.getElementById('location-status');
    const locationDetails = document.getElementById('location-details');
    const locationAddress = document.getElementById('location-address');
    const locationCoords = document.getElementById('location-coords');
    const latitudeField = document.querySelector('#id_latitude');
    const longitudeField = document.querySelector('#id_longitude');
    const addressField = document.querySelector('#id_current_address');
    const submitBtn = document.querySelector('.submit-btn');

    
    let locationDetected = false;
    updateSubmitButton();

    detectBtn.addEventListener('click', function() {
        detectBtn.disabled = true;
        locationStatus.textContent = 'Detecting your location...';
        locationStatus.className = 'location-status';

        if (!navigator.geolocation) {
            showLocationError('Geolocation is not supported by this browser.');
            return;
        }

        navigator.geolocation.getCurrentPosition(
            
            async function(position) {
                const lat = position.coords.latitude;
                const lng = position.coords.longitude;
                
                
                latitudeField.value = lat;
                longitudeField.value = lng;
                
                
                locationCoords.textContent = `${lat.toFixed(6)}, ${lng.toFixed(6)}`;
                
                
                try {
                    const address = await getAddressFromCoords(lat, lng);
                    locationAddress.textContent = address;
                    addressField.value = address;
                } catch (error) {
                    
                    const descriptiveAddress = `Location at ${lat.toFixed(6)}, ${lng.toFixed(6)}`;
                    locationAddress.textContent = descriptiveAddress;
                    addressField.value = descriptiveAddress;
                }
                
                
                locationStatus.textContent = 'Location detected successfully!';
                locationStatus.className = 'location-status success';
                locationDetails.style.display = 'block';
                detectBtn.disabled = false;
                locationDetected = true;
                updateSubmitButton();
            },
            
            function(error) {
                let errorMessage = 'Unable to detect your location. ';
                
                switch(error.code) {
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
                        break;
                }
                
                showLocationError(errorMessage);
            },
            
            {
                enableHighAccuracy: true,
                timeout: 15000,
                maximumAge: 0
            }
        );
    });

    function showLocationError(message) {
        locationStatus.textContent = message;
        locationStatus.className = 'location-status error';
        detectBtn.disabled = false;
        locationDetected = false;
        updateSubmitButton();
    }

    async function getAddressFromCoords(lat, lng) {
        
        try {
            const response = await fetch(
                `https://nominatim.openstreetmap.org/reverse?format=json&lat=${lat}&lon=${lng}&zoom=18&addressdetails=1`
            );
            
            if (response.ok) {
                const data = await response.json();
                if (data.display_name && data.display_name !== '') {
                    return data.display_name;
                }
            }
        } catch (error) {
            console.log('OpenStreetMap geocoding failed, trying fallback...');
        }
        
        
        const googleApiKey = '{{ GOOGLE_MAPS_API_KEY }}'; 
        if (googleApiKey && googleApiKey !== '{{ GOOGLE_MAPS_API_KEY }}') {
            try {
                const response = await fetch(
                    `https://maps.googleapis.com/maps/api/geocode/json?latlng=${lat},${lng}&key=${googleApiKey}`
                );
                
                if (response.ok) {
                    const data = await response.json();
                    if (data.status === 'OK' && data.results.length > 0) {
                        return data.results[0].formatted_address;
                    }
                }
            } catch (error) {
                console.log('Google Geocoding failed');
            }
        }
        
        
        throw new Error('Could not retrieve address from coordinates');
    }

    function updateSubmitButton() {
        if (submitBtn) {
            if (!locationDetected) {
                submitBtn.disabled = true;
                submitBtn.title = 'Please detect your location first';
                submitBtn.style.opacity = '0.6';
                submitBtn.style.cursor = 'not-allowed';
            } else {
                submitBtn.disabled = false;
                submitBtn.title = '';
                submitBtn.style.opacity = '1';
                submitBtn.style.cursor = 'pointer';
            }
        }
    }

    // Add form validation
    const form = document.querySelector('.signup-form');
    if (form) {
        form.addEventListener('submit', function(e) {
            if (!locationDetected) {
                e.preventDefault();
                showLocationError('Location detection is required. Please detect your location before submitting.');
                detectBtn.scrollIntoView({ behavior: 'smooth', block: 'center' });
                
                
                const locationSection = document.querySelector('.form-section:nth-child(2)');
                locationSection.style.border = '2px solid #dc3545';
                locationSection.style.backgroundColor = '#fff5f5';
                
                setTimeout(() => {
                    locationSection.style.border = '';
                    locationSection.style.backgroundColor = '';
                }, 3000);
            }
        });
    }

   
});