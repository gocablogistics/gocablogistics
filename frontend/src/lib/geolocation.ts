/**
 * One-shot current-position lookup that works the same in the browser
 * (web dev, desktop) and inside the Tauri Android/iOS WebView. Native builds
 * go through @tauri-apps/plugin-geolocation — Android's WebView geolocation
 * API is unreliable/permission-flaky on its own, which is the whole reason
 * this plugin exists — everything else falls back to navigator.geolocation.
 */
import { isTauri } from "@tauri-apps/api/core";

export interface SimpleCoords {
  latitude: number;
  longitude: number;
}

export function getCurrentPosition(
  onSuccess: (coords: SimpleCoords) => void,
  onError: () => void,
): void {
  if (isTauri()) {
    void getCurrentPositionNative(onSuccess, onError);
    return;
  }
  if (!("geolocation" in navigator)) {
    onError();
    return;
  }
  navigator.geolocation.getCurrentPosition(
    (pos) => onSuccess({ latitude: pos.coords.latitude, longitude: pos.coords.longitude }),
    () => onError(),
  );
}

async function getCurrentPositionNative(
  onSuccess: (coords: SimpleCoords) => void,
  onError: () => void,
): Promise<void> {
  try {
    const geo = await import("@tauri-apps/plugin-geolocation");
    let permission = await geo.checkPermissions();
    if (permission.location !== "granted") {
      permission = await geo.requestPermissions(["location"]);
    }
    if (permission.location !== "granted") {
      onError();
      return;
    }
    const pos = await geo.getCurrentPosition();
    onSuccess({ latitude: pos.coords.latitude, longitude: pos.coords.longitude });
  } catch {
    onError();
  }
}
