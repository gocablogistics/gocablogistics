import { apiRequest, API_BASE_URL, NGROK_HEADERS } from "./http";

export type Role = "rider" | "driver";

export interface UserOut {
  id: number;
  role: Role;
  full_name: string;
  phone_number: string;
  email?: string | null;
  is_approved?: boolean | null;
  address?: string | null;
  // Riders only — null for a driver account.
  referral_code?: string | null;
  wallet_credit_balance?: number | null;
}

export interface TokenPairOut {
  access: string;
  refresh: string;
  token_type: string;
  user: UserOut;
}

export interface RefreshOut {
  access: string;
  refresh: string;
  token_type: string;
}

export interface MessageOut {
  detail: string;
}

export function requestCode(email: string) {
  return apiRequest<MessageOut>("/auth/request-code", {
    method: "POST",
    body: { email },
  });
}

export function verifyCode(email: string, code: string) {
  return apiRequest<TokenPairOut>("/auth/verify-code", {
    method: "POST",
    body: { email, code },
  });
}

export interface RiderRegisterIn {
  full_name: string;
  phone_number: string;
  email: string;
  address?: string;
  // Exactly one of these is required — verified_token if the email was
  // already OTP-verified during a login attempt that turned out to be a
  // new user (see Login.tsx's 404 handling), a fresh code otherwise.
  code?: string;
  verified_token?: string;
  latitude?: number;
  longitude?: number;
  // Another rider's referral code, if they were invited by one — see
  // Referrals.tsx. Invalid codes are rejected server-side with a clear
  // error rather than silently ignored.
  referral_code?: string;
}

export function registerRider(payload: RiderRegisterIn) {
  return apiRequest<TokenPairOut>("/auth/register/rider", {
    method: "POST",
    body: payload,
  });
}

export interface DriverRegisterFields {
  full_name: string;
  email: string;
  phone_number: string;
  // Exactly one of these is required — verified_token if the email was
  // already OTP-verified during a login attempt that turned out to be a
  // new user (see Login.tsx's 404 handling), a fresh code otherwise.
  code?: string;
  verified_token?: string;
  date_of_birth: string; // YYYY-MM-DD
  national_identification_number: string;
  vehicle_type: "Bike" | "Bicycle";
  vehicle_color: string;
  // Bike-only — a Bicycle only ever sets vehicle_type/vehicle_color plus
  // the vehicle_picture upload. Enforced in the UI and again server-side.
  vehicle_model?: string;
  vehicle_brand?: string;
  production_year?: number;
  license_plate?: string;
  bank_name: string;
  bank_code?: string;
  account_number: string;
  account_holder_name: string;
  latitude: number;
  longitude: number;
  current_address?: string;
}

export interface BankOption {
  name: string;
  code: string;
}

/** Public, unauthenticated — the driver signup form needs this before the
 * driver has an account. Never rejects; an empty list just falls back to
 * whatever the caller renders for that case. */
export function getBankOptions(): Promise<BankOption[]> {
  return fetch(`${API_BASE_URL}/config/banks`, { headers: NGROK_HEADERS })
    .then((r) => r.json())
    .then((data) => data.banks ?? [])
    .catch(() => []);
}

export interface DriverRegisterFiles {
  drivers_license: File;
  passport_photo: File;
  nin_slip_photo: File;
  vehicle_picture: File;
}

export function registerDriver(
  fields: DriverRegisterFields,
  files: DriverRegisterFiles,
) {
  const form = new FormData();
  Object.entries(fields).forEach(([key, value]) => {
    if (value !== undefined && value !== null) {
      form.append(key, String(value));
    }
  });
  Object.entries(files).forEach(([key, file]) => {
    form.append(key, file);
  });
  return apiRequest<MessageOut>("/auth/register/driver", {
    method: "POST",
    body: form,
    isForm: true,
  });
}

export function refreshTokenPair(refresh: string) {
  return apiRequest<RefreshOut>("/auth/refresh", {
    method: "POST",
    body: { refresh },
  });
}

export function logout(refresh: string) {
  return apiRequest<MessageOut>("/auth/logout", {
    method: "POST",
    body: { refresh },
  });
}

export function deleteAccount(accessToken: string) {
  return apiRequest<MessageOut>("/auth/delete-account", {
    method: "POST",
    accessToken,
  });
}

export function me(accessToken: string) {
  return apiRequest<UserOut>("/auth/me", {
    method: "GET",
    accessToken,
  });
}
