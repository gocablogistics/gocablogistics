import { apiRequest } from "./http";
import { WS_BASE_URL } from "./rides";

export interface NotificationOut {
  id: number;
  message: string;
  created_at: string;
  is_active: boolean;
}

export function getNotifications(accessToken: string) {
  return apiRequest<NotificationOut[]>("/notifications", { accessToken });
}

export function getNotificationCount(accessToken: string) {
  return apiRequest<{ count: number }>("/notifications/count", { accessToken });
}

export function markNotificationRead(id: number, accessToken: string) {
  return apiRequest<{ count: number }>(`/notifications/${id}/read`, {
    method: "POST",
    accessToken,
  });
}

export function markAllNotificationsRead(accessToken: string) {
  return apiRequest<{ count: number }>("/notifications/read-all", {
    method: "POST",
    accessToken,
  });
}

export function notificationsSocketUrl(accessToken: string) {
  return `${WS_BASE_URL}/ws/notifications/?token=${encodeURIComponent(accessToken)}`;
}

// The platform field doesn't affect push delivery at all — Firebase Admin
// SDK routes by the token's own format, not this stored string — but it was
// hardcoded to "android" unconditionally, so every iOS DeviceToken row was
// mislabeled (visible in Django admin, would throw off any platform-split
// metric later). No @tauri-apps/plugin-os dependency here for one cosmetic
// field — the user agent is already a reliable, zero-dependency way to tell
// WKWebView from Android's WebView apart.
function detectPlatform(): string {
  if (typeof navigator === "undefined") return "android";
  return /iPhone|iPad|iPod/.test(navigator.userAgent) ? "ios" : "android";
}

export function registerDevice(
  token: string,
  accessToken: string,
  platform = detectPlatform(),
  appVersion = "",
) {
  return apiRequest<{ status: string }>("/notifications/register-device", {
    method: "POST",
    accessToken,
    body: { token, platform, app_version: appVersion },
  });
}
