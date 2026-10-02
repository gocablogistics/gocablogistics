/** "180 m" under a kilometre (rounded to 10 m), "2.1 km" above. */
export function formatDistance(km: number): string {
  return km < 1 ? `${Math.max(10, Math.round((km * 1000) / 10) * 10)} m` : `${km.toFixed(1)} km`;
}
