/**
 * Thin JS bridge to the custom `gocab-native` Tauri/Kotlin plugin's
 * hardware-back-button support — same reasoning and style as nativePush.ts
 * (raw invoke/listen calls, no generated guest-js wrapper for a first-party
 * plugin that never gets published).
 */
import { invoke, isTauri } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";

/** Fires on every hardware back press (Android only — never emitted elsewhere). */
export async function onBackPressed(handler: () => void): Promise<UnlistenFn | null> {
  if (!isTauri()) return null;
  try {
    return await listen("plugin:gocab-native://back-pressed", () => handler());
  } catch {
    return null;
  }
}

/** Backgrounds the app (moveTaskToBack) — the confirmed "press back again to exit". */
export async function exitApp(): Promise<void> {
  if (!isTauri()) return;
  try {
    await invoke("plugin:gocab-native|exit_app");
  } catch {
    /* best-effort */
  }
}
