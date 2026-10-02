import { isTauri } from "@tauri-apps/api/core";

/** Opens a link outside the app — the phone's browser (or Google Maps app)
 * in the Android build, a new tab on the web. In the Android app a plain
 * link or window.open goes nowhere, so it has to use the opener plugin.
 * Resolves true when the link was handed off. */
export async function openExternal(url: string): Promise<boolean> {
  if (isTauri()) {
    try {
      const { openUrl } = await import("@tauri-apps/plugin-opener");
      await openUrl(url);
      return true;
    } catch {
      return false;
    }
  }
  window.open(url, "_blank", "noopener");
  return true;
}
