/**
 * Core fetch infrastructure — base URL, error types, and the shared request
 * wrapper used by every typed endpoint in the api/client/ modules.
 *
 * Security invariant (spec §7.3, §9.2):
 *   - Every request sends `credentials: 'include'` so the signed `HttpOnly`
 *     session cookie is attached automatically by the browser.
 *   - No credential is ever stored in or shipped with the frontend bundle.
 *     Authentication is done via the login handshake → cookie; the JS bundle
 *     never sees or forwards any raw secret.
 *
 * Error model:
 *   - `Unauthenticated` — thrown on any 401 response; the app detects this
 *     class to route the user to the login screen.
 *   - `ApiError`        — thrown on any other non-2xx response.
 *   - 2xx              — resolved to the parsed JSON body (typed).
 *
 * Allowed deps: none (leaf module — CODE_GUIDELINES §12.3).
 */

/** The base URL for all API calls. Same-origin in production; proxied in dev. */
export const BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? '';

// ---------------------------------------------------------------------------
// Error types
// ---------------------------------------------------------------------------

/**
 * Thrown when the server returns a 401 Unauthorised response.
 *
 * The app detects `instanceof Unauthenticated` to redirect to the login screen.
 * This is deliberately NOT a subclass of `ApiError` so the two cases are
 * structurally distinct at the catch site.
 */
export class Unauthenticated extends Error {
  readonly status = 401 as const;

  constructor(message = 'Unauthenticated — please log in') {
    super(message);
    this.name = 'Unauthenticated';
    // Restore the prototype chain (required when transpiling to ES5).
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

/**
 * Thrown when the server returns a non-2xx, non-401 response.
 *
 * Carries the HTTP status code for the caller to inspect.
 */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message = `API error ${status}`) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

// ---------------------------------------------------------------------------
// Internal fetch helper
// ---------------------------------------------------------------------------

/**
 * Core fetch wrapper: attaches `credentials: 'include'`, normalises errors,
 * and returns the parsed JSON body typed as `T`.
 *
 * The `credentials: 'include'` flag ensures the signed `HttpOnly` session
 * cookie is sent with every cross-origin same-site request. Because the
 * cookie is `HttpOnly` the JS bundle cannot read or forward the raw key —
 * the browser is the only entity that sees it.
 *
 * A 202/204 response carries no body — `request` resolves to `undefined`
 * rather than attempting to parse one. An endpoint that returns no content
 * is typed `request<void>`.
 *
 * Additionally, a body-presence check guards against future endpoints that
 * return 200 with an empty body (e.g. a 304-equivalent or a no-content 200):
 * reading an empty body as JSON would throw a `SyntaxError`. The guard reads
 * the text first and skips JSON parsing when the body is empty.
 */
export async function request<T>(url: string, init: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    credentials: 'include',
  });

  if (!response.ok) {
    if (response.status === 401) {
      throw new Unauthenticated();
    }
    throw new ApiError(response.status);
  }

  // 202 Accepted / 204 No Content explicitly carry no body.
  if (response.status === 202 || response.status === 204) {
    return undefined as T;
  }

  // Guard against an empty body on any other 2xx — a `content-length: 0`
  // header or an actually-empty body both indicate no JSON to parse.
  const contentLength = response.headers.get('content-length');
  if (contentLength === '0') {
    return undefined as T;
  }

  const text = await response.text();
  if (text.trim().length === 0) {
    return undefined as T;
  }

  try {
    return JSON.parse(text) as T;
  } catch {
    // A non-JSON 2xx body (proxy error page, CDN HTML, etc.) must not surface
    // as a raw SyntaxError ("Unexpected token <") — throw a typed ApiError so
    // the app's error-handling path handles it uniformly.
    throw new ApiError(response.status, 'Server returned a non-JSON response');
  }
}
