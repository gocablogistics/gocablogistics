import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";

export async function getFcmToken(): Promise<string | null> {
  return await invoke<{ token?: string }>("plugin:gocab-native|get_fcm_token").then(
    (r) => r.token ?? null,
  );
}

export interface PushReceivedEvent {
  rideId: string | null;
  title: string | null;
  body: string | null;
}

/** Fires while the app is open and a push arrives — the OS-level system
 * notification (tap-to-open) is handled natively regardless of this. */
export function onPushReceived(
  handler: (event: PushReceivedEvent) => void,
): Promise<UnlistenFn> {
  return listen<PushReceivedEvent>("plugin:gocab-native://push-received", (e) => handler(e.payload));
}

/** Fires whenever FCM issues a new/rotated token — re-register it with the backend. */
export function onTokenRefresh(handler: (token: string) => void): Promise<UnlistenFn> {
  return listen<{ token: string }>("plugin:gocab-native://token-refresh", (e) =>
    handler(e.payload.token),
  );
}
