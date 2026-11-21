/**
 * Base URL, error types and the shared request wrapper behind every endpoint.
 *
 * A 401 throws `Unauthenticated` (the app routes to login); any other non-2xx
 * throws `ApiError`; a 2xx resolves to the parsed JSON body.
 */

/** The base URL for all API calls. Same-origin in production; proxied in dev. */
export const BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? '';

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

/**
 * Fetch with `credentials: 'include'`, normalise errors and return the JSON body as `T`.
 *
 * The session cookie is `HttpOnly`, so only the browser ever sees it. A 202, a
 * 204 or an empty 2xx body resolves to `undefined` (type such endpoints
 * `request<void>`) instead of failing in `JSON.parse`.
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

  if (response.status === 202 || response.status === 204) {
    return undefined as T;
  }

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
    // A non-JSON 2xx body (e.g. a proxy error page) becomes an ApiError, not a raw SyntaxError.
    throw new ApiError(response.status, 'Server returned a non-JSON response');
  }
}
