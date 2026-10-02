import { apiRequest, API_BASE_URL } from "./http";

export interface FareEstimateOut {
  base_fare: number;
  distance_km: number;
  duration_min: number;
  distance_fare: number;
  time_fare: number;
  surge_multiplier: number;
  total_fare: number;
  vehicle_type: string;
  currency: string;
  /** Signed price lock — send it back when booking so the fare charged is the fare shown. */
  quote?: string | null;
}

export type VehicleType = "Bike" | "Bicycle";

export function estimateFare(pickup: string, destination: string, vehicleType: VehicleType = "Bike") {
  return apiRequest<FareEstimateOut>("/rides/estimate-fare", {
    method: "POST",
    body: { pickup, destination, vehicle_type: vehicleType },
  });
}

export interface RequestRideOut {
  ride_id: number;
  status: string;
  fare: number;
  distance_km: number;
  duration_min: number;
}

export function requestRide(
  currentLocation: string,
  destination: string,
  accessToken: string,
  options?: {
    recipientPhoneNumber?: string;
    paymentMethod?: "online" | "cash";
    fareQuote?: string | null;
    vehicleType?: VehicleType;
  },
) {
  return apiRequest<RequestRideOut>("/rides/request", {
    method: "POST",
    body: {
      current_location: currentLocation,
      destination,
      recipient_phone_number: options?.recipientPhoneNumber || undefined,
      payment_method: options?.paymentMethod,
      fare_quote: options?.fareQuote || undefined,
      vehicle_type: options?.vehicleType,
    },
    accessToken,
  });
}

export interface DriverInfoOut {
  id: number;
  name: string;
  phone: string;
  car_model: string;
  license_plate: string;
  rating: number;
  photo?: string | null;
  latitude: number | null;
  longitude: number | null;
}

export interface ActiveRideOut {
  ride_id: number;
  status: string;
  requested_at: string;
  current_location: string;
  destination: string;
  pickup_latitude: number | null;
  pickup_longitude: number | null;
  destination_latitude: number | null;
  destination_longitude: number | null;
  total_fare: number | null;
  payment_status: string;
  payment_method: string;
  driver: DriverInfoOut | null;
  // Only present while the driver is heading to the pickup point.
  pickup_eta_min?: number | null;
  driver_distance_km?: number | null;
  // A no-login link to forward to whoever's actually receiving the
  // package — only set while the ride is still in flight (pending/
  // accepted/started). See pages/Track.tsx.
  tracking_url?: string | null;
}

export function getActiveRide(accessToken: string) {
  return apiRequest<ActiveRideOut>("/rides/active", { accessToken });
}

export function cancelRide(rideId: number, accessToken: string) {
  return apiRequest<{ detail: string }>(`/rides/${rideId}/cancel`, {
    method: "POST",
    accessToken,
  });
}

export interface InitiatePaymentOut {
  status: string;
  payment_url?: string;
  ride_id?: number;
  error?: string;
  // Wallet credit fully covered the fare — the ride is already marked paid
  // and there's no Paystack checkout to redirect to at all.
  paid_via_wallet_credit?: boolean;
  wallet_credit_applied?: string;
}

export function initiatePayment(rideId: number, accessToken: string) {
  return apiRequest<InitiatePaymentOut>(`/rides/${rideId}/pay`, {
    method: "POST",
    accessToken,
  });
}

export interface CashPaymentOut {
  status: string;
  code?: string;
  ride_id?: number;
  error?: string;
}

export function payCash(rideId: number, accessToken: string) {
  return apiRequest<CashPaymentOut>(`/rides/${rideId}/pay-cash`, {
    method: "POST",
    accessToken,
  });
}

export interface ConfirmCashOut {
  status: string;
  message?: string;
  error?: string;
  ride_id?: number;
}

export function confirmCash(rideId: number, code: string, accessToken: string) {
  return apiRequest<ConfirmCashOut>(`/rides/${rideId}/confirm-cash`, {
    method: "POST",
    body: { code },
    accessToken,
  });
}

export function reportNonPayment(rideId: number, accessToken: string, reason: string = "") {
  return apiRequest<{ status: string; message?: string; error?: string }>(
    `/rides/${rideId}/report-nonpayment`,
    { method: "POST", body: { reason }, accessToken },
  );
}

export function reportDriver(rideId: number, accessToken: string, reason: string) {
  return apiRequest<{ status: string; message?: string; error?: string }>(
    `/rides/${rideId}/report-driver`,
    { method: "POST", body: { reason }, accessToken },
  );
}

export function respondToDispute(rideId: number, statement: string, accessToken: string) {
  return apiRequest<{ status: string; message?: string; error?: string }>(
    `/rides/${rideId}/dispute/respond`,
    { method: "POST", body: { statement }, accessToken },
  );
}

export interface PaymentCallbackOut {
  ride_id: number;
  payment_status: string;
  total_fare: number | null;
  paid_at: string | null;
  wallet_credit_applied: number | null;
}

export function confirmPayment(
  rideId: number,
  accessToken: string,
  reference?: string,
  confirmToken?: string | null,
) {
  const params = new URLSearchParams();
  if (reference) params.set("reference", reference);
  // Proves this is the same checkout that was just started, regardless of
  // which account this browser tab is currently logged into by the time
  // Paystack's redirect reloads the page — see utils/payment_confirm.py.
  if (confirmToken) params.set("confirm_token", confirmToken);
  const query = params.toString() ? `?${params.toString()}` : "";
  return apiRequest<PaymentCallbackOut>(`/rides/${rideId}/payment-callback${query}`, {
    accessToken,
  });
}

export interface RateRideOut {
  status: string;
  average_rating?: number;
  error?: string;
}

export function rateRide(
  rideId: number,
  stars: number,
  accessToken: string,
  comment: string = "",
) {
  return apiRequest<RateRideOut>(`/rides/${rideId}/rate`, {
    method: "POST",
    body: { stars, comment },
    accessToken,
  });
}

/** Websocket base derived from the same host/port as the JSON API. When
 * API_BASE_URL is a relative path (e.g. "/api/v1", used when Vite is
 * proxying to the backend — see vite.config.ts — so a single ngrok tunnel
 * on the frontend port covers both), there's no host to strip a protocol
 * off, so it's derived from the page's own origin instead; Vite's proxy
 * forwards the WS upgrade the same way it forwards /api. */
export const WS_BASE_URL = /^https?:\/\//.test(API_BASE_URL)
  ? API_BASE_URL.replace(/^http/, "ws").replace(/\/api\/v1$/, "")
  : `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}`;

export function rideUpdatesSocketUrl(accessToken: string) {
  return `${WS_BASE_URL}/ws/ride/updates/?token=${encodeURIComponent(accessToken)}`;
}

export interface RideMessageOut {
  id: number;
  ride_id: number;
  sender_id: number;
  sender_role: "rider" | "driver";
  text: string;
  created_at: string;
}

export function getRideMessages(rideId: number, accessToken: string) {
  return apiRequest<RideMessageOut[]>(`/rides/${rideId}/messages`, { accessToken });
}

export function sendRideMessage(rideId: number, text: string, accessToken: string) {
  return apiRequest<RideMessageOut>(`/rides/${rideId}/messages`, {
    method: "POST",
    body: { text },
    accessToken,
  });
}

// ── Driver-side ──────────────────────────────────────────────────────────────

export interface AvailabilityOut {
  is_online: boolean;
  is_busy: boolean;
}

export function getAvailability(accessToken: string) {
  return apiRequest<AvailabilityOut>("/rides/availability", { accessToken });
}

export function setAvailability(isOnline: boolean, accessToken: string) {
  return apiRequest<AvailabilityOut>("/rides/availability", {
    method: "POST",
    body: { is_online: isOnline },
    accessToken,
  });
}

export interface NearbyRideOut {
  id: number;
  current_location: string;
  destination: string;
  pickup_latitude: number | null;
  pickup_longitude: number | null;
  total_fare: number | null;
  vehicle_type: string;
  distance_from_driver: number | null;
  estimated_pickup_time: number | null;
  requested_at: string;
  passenger_name: string;
  passenger_phone: string;
  passenger_rating: number;
}

export function getNearbyRides(accessToken: string) {
  return apiRequest<NearbyRideOut[]>("/rides/nearby", { accessToken });
}

export function acceptRide(rideId: number, accessToken: string) {
  return apiRequest<{ status: string; message?: string }>(`/rides/${rideId}/accept`, {
    method: "POST",
    accessToken,
  });
}

export function startTrip(rideId: number, accessToken: string) {
  return apiRequest<{ status: string; message?: string }>(`/rides/${rideId}/start`, {
    method: "POST",
    accessToken,
  });
}

export function completeTrip(rideId: number, accessToken: string) {
  return apiRequest<{ status: string; message?: string }>(`/rides/${rideId}/complete`, {
    method: "POST",
    accessToken,
  });
}

export function driverCancelRide(rideId: number, accessToken: string) {
  return apiRequest<{ status: string; message?: string }>(`/rides/${rideId}/driver-cancel`, {
    method: "POST",
    accessToken,
  });
}

export function updateDriverLocation(
  latitude: number,
  longitude: number,
  accessToken: string,
) {
  return apiRequest<{ detail: string }>("/rides/location", {
    method: "POST",
    body: { latitude, longitude },
    accessToken,
  });
}

export function updateRiderLocation(
  latitude: number,
  longitude: number,
  accessToken: string,
) {
  return apiRequest<{ detail: string }>("/rides/rider-location", {
    method: "POST",
    body: { latitude, longitude },
    accessToken,
  });
}

export interface PassengerInfoOut {
  name: string;
  phone: string;
  rating: number;
  latitude: number | null;
  longitude: number | null;
}

export interface DriverActiveRideOut {
  ride_id: number;
  status: string;
  current_location: string;
  destination: string;
  pickup_latitude: number | null;
  pickup_longitude: number | null;
  destination_latitude: number | null;
  destination_longitude: number | null;
  total_fare: number | null;
  payment_status: string;
  payment_method: string;
  // Only present while heading to the pickup point.
  pickup_eta_min?: number | null;
  pickup_distance_km?: number | null;
  passenger: PassengerInfoOut;
}

export function getDriverActiveRide(accessToken: string) {
  return apiRequest<DriverActiveRideOut>("/rides/driver/active", { accessToken });
}

export interface DriverSummaryOut {
  completed_trips: number;
  completion_rate: number;
  todays_earnings: number;
  total_earnings: number;
  cash_debt: number;
  cash_debt_blocked: boolean;
  is_flagged: boolean;
  // Card-ride earnings not yet paid out, weekly or instant.
  wallet_balance: number;
}

export function getDriverSummary(accessToken: string) {
  return apiRequest<DriverSummaryOut>("/rides/driver/summary", { accessToken });
}

export interface PayoutOut {
  id: number;
  ride_id: number;
  amount: number;
  status: string;
  created_at: string;
  paid_at: string | null;
}

export function getDriverPayouts(accessToken: string) {
  return apiRequest<PayoutOut[]>("/rides/driver/payouts", { accessToken });
}

export interface CashoutOut {
  status: string;
  amount?: number;
  fee?: number;
  batch_id?: number;
  error?: string;
}

// Instant cash-out of the driver's current wallet_balance, minus
// settings.INSTANT_CASHOUT_FEE (see flags.instant_cashout_fee) — same model
// as Uber's Flex Pay. A rejection (nothing to cash out, balance too small)
// comes back as a normal ApiError via apiRequest's existing handling.
export function cashOutNow(accessToken: string) {
  return apiRequest<CashoutOut>("/rides/driver/cashout", { method: "POST", accessToken });
}

export interface ReferralOut {
  full_name: string;
  joined_at: string;
  reward_earned: boolean;
}

export interface ReferralSummaryOut {
  referral_code: string;
  wallet_credit_balance: number;
  referral_reward_amount: number;
  referrals: ReferralOut[];
}

export function getReferrals(accessToken: string) {
  return apiRequest<ReferralSummaryOut>("/rides/referrals", { accessToken });
}

export interface RideHistoryOut {
  ride_id: number;
  current_location: string;
  destination: string;
  status: string;
  payment_status: string;
  payment_method: string;
  total_fare: number | null;
  distance_km: number | null;
  requested_at: string;
  completed_at: string | null;
  other_party_name: string | null;
  my_rating_submitted: boolean;
}

export function getRideHistory(accessToken: string) {
  return apiRequest<RideHistoryOut[]>("/rides/history", { accessToken });
}

export function getDriverRideHistory(accessToken: string) {
  return apiRequest<RideHistoryOut[]>("/rides/driver/history", { accessToken });
}

export interface TrackingOut {
  status: string;
  destination: string;
  vehicle_type: string;
  driver_name: string | null;
  driver_photo: string | null;
  driver_latitude: number | null;
  driver_longitude: number | null;
  destination_latitude: number | null;
  destination_longitude: number | null;
  pickup_eta_min: number | null;
}

// Public, unauthenticated — no accessToken, same as estimateFare. Used by
// pages/Track.tsx, which a recipient opens with no GoCab account at all.
export function getTracking(token: string) {
  return apiRequest<TrackingOut>(`/rides/track/${token}`);
}
