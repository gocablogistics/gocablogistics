export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000/api/v1";

// ngrok's free tier answers browser-like requests with an HTML warning page
// instead of the API's JSON unless this header is present. Only sent when the
// app is actually pointed at an ngrok address — on a real host it would just
// force an extra CORS preflight the server has no reason to allow-list.
export const NGROK_HEADERS: Record<string, string> = API_BASE_URL.includes("ngrok")
  ? { "ngrok-skip-browser-warning": "1" }
  : {};

// Pydantic/Ninja validation failures (422s) shape "detail" as an array of
// {type, loc, msg, ctx} objects rather than a plain string — extract a
// readable sentence from it instead of falling through to a generic message.
// Custom field_validator ValueErrors also get a "Value error, " prefix
// prepended by Pydantic, which reads badly to an end user, so it's stripped.
function messageFromValidationErrors(detail: unknown): string | null {
  if (!Array.isArray(detail) || detail.length === 0) return null;
  const messages = detail
    .map((item) => (item && typeof item === "object" ? (item as { msg?: unknown }).msg : null))
    .filter((msg): msg is string => typeof msg === "string" && msg.length > 0)
    .map((msg) => msg.replace(/^Value error,\s*/i, ""));
  return messages.length > 0 ? messages.join(" ") : null;
}

const GENERIC_ERROR_MESSAGE = "Something went wrong. Please try again.";

export class ApiError extends Error {
  status: number;
  body: unknown;
  /** Set only on the generic unhandled-exception response (api/main.py's
   * handle_unexpected_exception) — a Sentry event id a developer can look
   * up directly, or null if Sentry isn't configured yet. */
  errorId: string | null;

  constructor(status: number, body: unknown) {
    // Backend error shapes aren't fully consistent — Ninja/auth endpoints
    // use {"detail": ...} (a string for hand-written errors, an array of
    // validation-error objects for Pydantic-rejected input), the
    // service-layer action endpoints (accept, start, complete, cancel,
    // pay-cash, confirm-cash, ...) use either {"error": ...} or
    // {"message": ...} depending on which function wrote it. Check all of
    // these rather than silently falling back to a generic message.
    let detail = GENERIC_ERROR_MESSAGE;
    let errorId: string | null = null;
    if (typeof body === "object" && body !== null) {
      const b = body as Record<string, unknown>;
      const found = b.detail ?? b.error ?? b.message;
      if (typeof found === "string" && found) {
        detail = found;
      } else {
        const fromValidation = messageFromValidationErrors(found);
        if (fromValidation) detail = fromValidation;
      }
      if (typeof b.error_id === "string") errorId = b.error_id;
    }
    super(import.meta.env.DEV && errorId ? `${detail} (Ref: ${errorId})` : detail);
    this.status = status;
    this.body = body;
    this.errorId = errorId;
  }
}

type RequestOptions = {
  method?: string;
  body?: unknown;
  isForm?: boolean;
  accessToken?: string | null;
};

export async function apiRequest<T>(
  path: string,
  { method = "GET", body, isForm = false, accessToken }: RequestOptions = {},
): Promise<T> {
  const headers: Record<string, string> = { ...NGROK_HEADERS };
  if (accessToken) {
    headers["Authorization"] = `Bearer ${accessToken}`;
  }
  let requestBody: BodyInit | undefined;
  if (body !== undefined) {
    if (isForm) {
      requestBody = body as FormData;
    } else {
      headers["Content-Type"] = "application/json";
      requestBody = JSON.stringify(body);
    }
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    method,
    headers,
    body: requestBody,
  });

  const contentType = response.headers.get("content-type") ?? "";
  const responseBody = contentType.includes("application/json")
    ? await response.json()
    : await response.text();

  if (!response.ok) {
    throw new ApiError(response.status, responseBody);
  }
  return responseBody as T;
}
