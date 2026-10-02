import { API_BASE_URL, NGROK_HEADERS } from "./http";

declare global {
  interface Window {
    google?: typeof google;
  }
}

let loadPromise: Promise<boolean> | null = null;

/** Fetch the Maps key from the backend, inject the script tag, resolve
 * true once google.maps.places is ready — same script-injection pattern
 * the legacy rider-dashboard-2.html already uses. Resolves false (never
 * rejects) on any failure so callers can fall back to plain inputs. */
export function loadGoogleMaps(): Promise<boolean> {
  if (window.google?.maps?.places) return Promise.resolve(true);
  if (loadPromise) return loadPromise;

  loadPromise = fetch(`${API_BASE_URL}/config/maps-key`, { headers: NGROK_HEADERS })
    .then((r) => r.json())
    .then(
      (data) =>
        new Promise<boolean>((resolve) => {
          const key = data.key;
          if (!key) {
            resolve(false);
            return;
          }
          const existing = document.querySelector('script[src*="maps.googleapis.com"]');
          if (existing) {
            existing.addEventListener("load", () => resolve(!!window.google?.maps?.places));
            return;
          }
          const script = document.createElement("script");
          script.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(key)}&libraries=places`;
          script.async = true;
          script.defer = true;
          script.onload = () => resolve(!!window.google?.maps?.places);
          script.onerror = () => resolve(false);
          document.head.appendChild(script);
        }),
    )
    .catch(() => false)
    .then((ok) => {
      // A failed load must not be cached forever, or "Retry" could never work.
      if (!ok) loadPromise = null;
      return ok;
    });

  return loadPromise;
}

export const AUTOCOMPLETE_OPTIONS: google.maps.places.AutocompleteOptions = {
  types: ["address"],
  fields: ["formatted_address", "geometry", "place_id"],
  componentRestrictions: { country: "ng" },
};

// Shared dark map style, matching the app's dark theme wherever a live map
// is shown (BookingScreen, RideMap).
export const DARK_MAP_STYLE: google.maps.MapTypeStyle[] = [
  { elementType: "geometry", stylers: [{ color: "#1a1f1c" }] },
  { elementType: "labels.text.stroke", stylers: [{ color: "#1a1f1c" }] },
  { elementType: "labels.text.fill", stylers: [{ color: "#8a938e" }] },
  { featureType: "road", elementType: "geometry", stylers: [{ color: "#2c332e" }] },
  { featureType: "road", elementType: "labels.text.fill", stylers: [{ color: "#8a938e" }] },
  { featureType: "road.highway", elementType: "geometry", stylers: [{ color: "#3a4640" }] },
  { featureType: "poi", elementType: "geometry", stylers: [{ color: "#1f2622" }] },
  { featureType: "poi.park", elementType: "geometry", stylers: [{ color: "#22281f" }] },
  { featureType: "water", elementType: "geometry", stylers: [{ color: "#0b1a24" }] },
  { featureType: "administrative", elementType: "geometry.stroke", stylers: [{ color: "#2c332e" }] },
  { featureType: "transit", stylers: [{ visibility: "off" }] },
];
