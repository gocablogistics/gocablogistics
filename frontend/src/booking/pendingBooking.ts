import { requestRide } from "../api/rides";

const STORAGE_KEY = "gocab_pending_booking";

export interface PendingBooking {
  currentLocation: string;
  destination: string;
}

export function savePendingBooking(booking: PendingBooking) {
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify(booking));
}

export function getPendingBooking(): PendingBooking | null {
  const raw = sessionStorage.getItem(STORAGE_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as PendingBooking;
  } catch {
    return null;
  }
}

export function clearPendingBooking() {
  sessionStorage.removeItem(STORAGE_KEY);
}

export interface ResumeResult {
  resumed: boolean;
  rideId?: number;
  error?: string;
}

/**
 * Called right after login/signup succeeds. If the visitor described a
 * booking on the homepage before we made them authenticate, submit it now
 * instead of making them type it in again.
 *
 * Only meaningful for a rider — the backend's /rides/request doesn't check
 * role, so without this guard a driver logging in from the same tab would
 * accidentally create a ride request for themselves as a passenger. The
 * pending booking is left in place (not cleared) so it can still resume if
 * the same tab later logs in as the right kind of account.
 */
export async function resumePendingBookingIfAny(
  accessToken: string,
  role: string,
): Promise<ResumeResult> {
  if (role !== "rider") return { resumed: false };

  const pending = getPendingBooking();
  if (!pending) return { resumed: false };

  try {
    const ride = await requestRide(
      pending.currentLocation,
      pending.destination,
      accessToken,
    );
    clearPendingBooking();
    return { resumed: true, rideId: ride.ride_id };
  } catch (err) {
    clearPendingBooking();
    return {
      resumed: false,
      error:
        err instanceof Error
          ? err.message
          : "Could not complete your earlier booking.",
    };
  }
}
