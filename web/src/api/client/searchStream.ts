/**
 * Streaming search client for `POST /api/search/stream`, which streams the
 * pipeline's per-phase reasoning as NDJSON (one JSON object per line).
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
 * POST to `/api/search/stream` and return the raw `Response` for {@link parseNdjson}.
 *
 * A non-OK initial response throws before any body is read, with the same errors
 * as `request`: 401 → `Unauthenticated`, otherwise `ApiError` with the status
 * (503 drives the "index not ready" screen).
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
 * Decode an NDJSON byte stream into `StreamEvent`s.
 *
 * A line split across chunks is buffered until its newline arrives, and a final
 * line without a trailing newline is still emitted. Blank lines are skipped; a
 * line that is not valid JSON, or a `null` stream, raises a `StreamError`.
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

/** Parse one NDJSON line into a `StreamEvent`, or `null` for a blank line. */
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
