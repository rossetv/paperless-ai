/**
 * Defensive accessors over a phase record's free-form `detail` map.
 *
 * `detail` is wire JSON — any key may be missing or wrong-typed. Every reader
 * here returns a safe fallback (null / [] / false) rather than throwing, so a
 * malformed payload simply renders nothing. Split out of `phaseStages` (FE-01)
 * so the per-phase renderer stays under the file-length ceiling.
 *
 * Allowed deps: api/types only (CODE_GUIDELINES §12.3).
 */

import type { PhaseRecord } from '../../../api/types';
import type { StageVerdict } from '../../../components/primitives/PipelineStages/PipelineStages';

/** Read a key as a string, or null for any other shape. */
export function str(detail: Record<string, unknown>, key: string): string | null {
  const value = detail[key];
  return typeof value === 'string' ? value : null;
}

/** Read a key as a number, or null for any other shape. */
export function num(detail: Record<string, unknown>, key: string): number | null {
  const value = detail[key];
  return typeof value === 'number' ? value : null;
}

/** Read a key as a strict boolean — true only when the value is exactly true. */
export function bool(detail: Record<string, unknown>, key: string): boolean {
  return detail[key] === true;
}

/** Read a key as a list of plain objects, or `[]` for any other shape. */
export function objList(
  detail: Record<string, unknown>,
  key: string,
): Record<string, unknown>[] {
  const value = detail[key];
  if (!Array.isArray(value)) {
    return [];
  }
  return value.map((entry) => (entry ?? {}) as Record<string, unknown>);
}

/** Read a key off a plain object as a string, or null. */
export function fieldStr(item: Record<string, unknown>, key: string): string | null {
  const value = item[key];
  return typeof value === 'string' ? value : null;
}

/** Read a key off a plain object as a number, or null. */
export function fieldNum(item: Record<string, unknown>, key: string): number | null {
  const value = item[key];
  return typeof value === 'number' ? value : null;
}

/** Read a key off a plain object as a list of strings, dropping non-strings. */
export function fieldStrList(item: Record<string, unknown>, key: string): string[] {
  const value = item[key];
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((entry): entry is string => typeof entry === 'string');
}

/** Read a key off a plain object as a list of numbers, dropping non-numbers. */
export function fieldNumList(item: Record<string, unknown>, key: string): number[] {
  const value = item[key];
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((entry): entry is number => typeof entry === 'number');
}

/** Read a nested object field as a plain record, or null for any other shape. */
export function fieldObj(
  item: Record<string, unknown>,
  key: string,
): Record<string, unknown> | null {
  const value = item[key];
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

/** Read the judge's per-document verdicts from a judge phase's `detail`. */
export function verdictsOf(record: PhaseRecord): StageVerdict[] | undefined {
  if (record.phase !== 'judge') {
    return undefined;
  }
  const raw = record.detail['verdicts'];
  if (!Array.isArray(raw)) {
    return undefined;
  }
  return raw.map((entry): StageVerdict => {
    const item = (entry ?? {}) as Record<string, unknown>;
    return {
      docId: typeof item['doc_id'] === 'number' ? item['doc_id'] : 0,
      title: typeof item['title'] === 'string' ? item['title'] : null,
      keep: item['keep'] === true,
      reason: typeof item['reason'] === 'string' ? item['reason'] : '',
      score: typeof item['score'] === 'number' ? item['score'] : null,
      paperlessUrl:
        typeof item['paperless_url'] === 'string' ? item['paperless_url'] : null,
    };
  });
}
