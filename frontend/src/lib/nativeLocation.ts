/**
 * Bridge to gocab-native's background location half — a real Android
 * foreground service (GocabLocationService) that keeps posting the driver's
 * location to the backend even while the app is backgrounded, which the
 * JS-side geolocation ping in DriverHome can't do once Android suspends the
 * WebView. No-op everywhere else (desktop/web), same as lib/nativePush.
 */
import { invoke, isTauri } from "@tauri-apps/api/core";

export async function startLocationTracking(baseUrl: string, token: string): Promise<void> {
  if (!isTauri()) return;
  try {
    await invoke("plugin:gocab-native|start_location_tracking", {
      payload: { baseUrl, token },
    });
  } catch {
    // Most likely missing location permission — the foreground JS ping
    // still covers the app-open case either way.
  }
}

export async function stopLocationTracking(): Promise<void> {
  if (!isTauri()) return;
  try {
    await invoke("plugin:gocab-native|stop_location_tracking");
  } catch {
    /* best-effort */
  }
}

export async function updateLocationToken(token: string): Promise<void> {
  if (!isTauri()) return;
  try {
    await invoke("plugin:gocab-native|update_location_token", { payload: { token } });
  } catch {
    /* best-effort */
  }
}
