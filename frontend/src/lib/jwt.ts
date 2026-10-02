/** Reads the user id straight out of a JWT access token's payload, with no
 * network call and no signature check — this is only ever used for "whose
 * message is this" style UI decisions on the same device that already holds
 * the token; every real permission check still happens server-side against
 * the verified token. Exists so identity for the UI doesn't depend on the
 * separate /auth/me call succeeding (see AuthContext) — a token that's
 * valid enough to authenticate every other request is valid enough to read
 * a user id out of. Matches NINJA_JWT's USER_ID_CLAIM = "user_id". */
export function decodeAccessTokenUserId(token: string | null): number | null {
  if (!token) return null;
  try {
    const payload = token.split(".")[1];
    if (!payload) return null;
    const base64 = payload.replace(/-/g, "+").replace(/_/g, "/");
    const padded = base64 + "=".repeat((4 - (base64.length % 4)) % 4);
    const json = JSON.parse(atob(padded));
    const id = json.user_id;
    return typeof id === "number" ? id : Number(id) || null;
  } catch {
    return null;
  }
}
