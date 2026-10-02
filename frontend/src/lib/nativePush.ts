/**
 * Thin JS bridge to the custom `gocab-native` Tauri/Kotlin plugin
 * (frontend/src-tauri/plugins/tauri-plugin-gocab-native). Calls invoke/listen
 * directly with the plugin's raw command/event names rather than going
 * through that plugin's own guest-js package — it's a first-party plugin
 * that never gets published, so a separate rollup build for its wrapper
 * would just be overhead.
 */
import { invoke, isTauri } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";

export async function getFcmToken(): Promise<string | null> {
  if (!isTauri()) return null;
  try {
    const result = await invoke<{ token?: string }>("plugin:gocab-native|get_fcm_token");
    return result.token ?? null;
  } catch {
    return null;
  }
}

/** Asks Android 13+ for notification permission (no-op elsewhere). Without
 * this the app never shows the system prompt and every push is silently dropped. */
export async function requestNotificationPermission(): Promise<void> {
  if (!isTauri()) return;
  try {
    await invoke("plugin:gocab-native|request_notification_permission");
  } catch {
    /* best-effort */
  }
}

export interface PushReceivedEvent {
  rideId: string | null;
  title: string | null;
  body: string | null;
}

export async function onPushReceived(
  handler: (event: PushReceivedEvent) => void,
): Promise<UnlistenFn | null> {
  if (!isTauri()) return null;
  try {
    return await listen<PushReceivedEvent>("plugin:gocab-native://push-received", (e) =>
      handler(e.payload),
    );
  } catch {
    return null;
  }
}

export async function onTokenRefresh(handler: (token: string) => void): Promise<UnlistenFn | null> {
  if (!isTauri()) return null;
  try {
    return await listen<{ token: string }>("plugin:gocab-native://token-refresh", (e) =>
      handler(e.payload.token),
    );
  } catch {
    return null;
  }
}
