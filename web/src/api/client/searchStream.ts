/**
 * Streaming search client — `POST /api/search/stream` (NDJSON).
 *
 * The agentic search pipeline streams its per-phase reasoning live as
 * `application/x-ndjson`: one JSON object per `\n`-terminated line. This module
 * has two halves:
 *
 *   - `streamSearch(body, signal?)` — fires the POST and, on a 2xx, returns the
 *     raw `Response` so the caller can read its `body` stream. On a NON-OK
 *     *initial* response it throws the SAME typed errors as the JSON `request`
 *     wrapper (`Unauthenticated` for 401, `ApiError` carrying the status for
 *     anything else) so `SearchPage` can reproduce the existing 401 → login and
 *     503 → "index not ready" behaviour. The status is surfaced BEFORE any
 *     streaming begins — a non-OK response never has a body to stream.
 *   - `parseNdjson(stream)` — an async generator that decodes the byte stream
 *     (a streaming UTF-8 `TextDecoder`), buffers a partial trailing line across
 *     chunk boundaries, splits on `\n`, and `JSON.parse`s each COMPLETE line
 *     into a `StreamEvent`, flushing any final buffered (newline-less) line
 *     when the stream ends.
 *
 * Security: mirrors `client/core.ts` — `credentials: 'include'` so the signed
 * `HttpOnly` session cookie is attached; the JS bundle never sees a raw secret.
 *
 * Allowed deps: core (error types + BASE_URL), types (leaf module —
 * CODE_GUIDELINES §12.3).
 */

import type { SearchRequest, StreamEvent } from '../types';
import { ApiError, BASE_URL, Unauthenticated } from './core';

/**
 * Thrown when the stream itself is malformed — a missing response body, or a
 * line that is not valid JSON. Distinct from `ApiError`/`Unauthenticated`
 * (which model the *initial* HTTP failure) so a transport-level corruption is
 * not mistaken for an auth or index-readiness signal.
 */
export class StreamError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'StreamError';
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

/**
 * POST to `/api/search/stream` and return the streaming `Response`.
 *
 * Resolves with the raw `Response` on a 2xx so the caller can pipe
 * `response.body` through {@link parseNdjson}. Throws on a non-OK *initial*
 * response, BEFORE any body is read:
 *   - 401 → `Unauthenticated` (drives `me`-invalidation → login redirect)
 *   - any other non-2xx → `ApiError` carrying the HTTP status (503 → the
 *     "index not ready" screen; everything else → the generic error screen).
 *
 * @param body   The search request (query + optional filters).
 * @param signal Optional `AbortSignal` to cancel the in-flight request.
 */
export async function streamSearch(
  body: SearchRequest,
  signal?: AbortSignal,
): Promise<Response> {
  const response = await fetch(`${BASE_URL}/api/search/stream`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    ...(signal ? { signal } : {}),
  });

  if (!response.ok) {
    if (response.status === 401) {
      throw new Unauthenticated();
    }
    throw new ApiError(response.status);
  }

  return response;
}

/**
 * Decode an NDJSON byte stream into a sequence of `StreamEvent`s.
 *
 * Reads the stream chunk by chunk, decoding UTF-8 with a streaming
 * `TextDecoder` (`{ stream: true }` carries a partial multi-byte character
 * across reads), accumulates text in a buffer, and emits one event per
 * `\n`-terminated line. A line that spans a chunk boundary stays in the buffer
 * until its newline arrives, so a frame split mid-line is reassembled
 * correctly. When the stream ends, the decoder is flushed and any final
 * buffered line (a terminal frame sent without a trailing newline) is emitted.
 *
 * Blank lines are skipped. A line that fails to `JSON.parse` raises a
 * `StreamError` — a corrupt frame is a hard failure, not a silently-dropped
 * one.
 *
 * @param stream The `Response.body` to read; `null` raises a `StreamError`.
 */
export async function* parseNdjson(
  stream: ReadableStream<Uint8Array> | null,
): AsyncGenerator<StreamEvent> {
  if (stream === null) {
    throw new StreamError('search stream had no response body');
  }

  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) {
        break;
      }
      // stream: true so a multi-byte char split across chunks is held back.
      buffer += decoder.decode(value, { stream: true });

      // Emit every COMPLETE line; keep the trailing partial in the buffer.
      let newlineIndex = buffer.indexOf('\n');
      while (newlineIndex !== -1) {
        const line = buffer.slice(0, newlineIndex);
        buffer = buffer.slice(newlineIndex + 1);
        const event = parseLine(line);
        if (event !== null) {
          yield event;
        }
        newlineIndex = buffer.indexOf('\n');
      }
    }

    // Flush the decoder, then emit a final newline-less line (a terminal frame
    // sent without a trailing "\n").
    buffer += decoder.decode();
    const tail = parseLine(buffer);
    if (tail !== null) {
      yield tail;
    }
  } finally {
    reader.releaseLock();
  }
}

/**
 * Parse one NDJSON line into a `StreamEvent`, or `null` for a blank line.
 *
 * A non-blank line that is not valid JSON raises a `StreamError`.
 */
function parseLine(line: string): StreamEvent | null {
  const trimmed = line.trim();
  if (trimmed.length === 0) {
    return null;
  }
  try {
    return JSON.parse(trimmed) as StreamEvent;
  } catch {
    throw new StreamError('malformed NDJSON frame in search stream');
  }
}
