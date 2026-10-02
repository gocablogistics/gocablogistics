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

export function registerDevice(
  token: string,
  accessToken: string,
  platform = "android",
  appVersion = "",
) {
  return apiRequest<{ status: string }>("/notifications/register-device", {
    method: "POST",
    accessToken,
    body: { token, platform, app_version: appVersion },
  });
}
