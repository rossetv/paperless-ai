/**
 * Shared rendering of search-trace phases as `PipelineStages` rows.
 *
 * The live `LoadingScreen` rail and the folded `SearchTracePanel` show the SAME
 * per-phase information — the planner's rewritten query, the retrieval counts,
 * the vector-gate outcome, the judge's per-document verdicts, the synthesis
 * mode, plus a token/cost chip on every LLM phase. This module is the single
 * source of that mapping, so the two surfaces never drift.
 *
 * `phaseToStages(records, activePhase)` turns the streamed `PhaseRecord[]` (plus
 * the currently-running phase, if any) into `PipelineStage[]`. A record's
 * free-form `detail` map is read defensively: a missing or wrong-typed key
 * simply renders nothing rather than throwing, since `detail` is wire JSON.
 *
 * Allowed deps: react, api/types, components/primitives (PipelineStages types),
 * components/primitives (Text), own CSS module (CODE_GUIDELINES §12.3).
 */

import React from 'react';
import type {
  Cost,
  CostSummary,
  PhaseRecord,
  SearchPhase,
  TokenUsage,
} from '../../../api/types';
import type {
  PipelineStage,
  PipelineStageState,
  StageVerdict,
} from '../../../components/primitives/PipelineStages/PipelineStages';
import styles from './phaseStages.module.css';

/** A human-readable label for each phase, used when streaming a `phase_start`
 *  before its done-record (which carries the server's own label) arrives. */
const PHASE_LABELS: Record<SearchPhase, string> = {
  plan: 'Planning the query',
  resolve: 'Resolving filters',
  retrieve: 'Retrieving documents',
  gate: 'Relevance gate',
  judge: 'Judging relevance',
  synthesise: 'Synthesising the answer',
  replan: 'Re-planning',
  refine: 'Refining the answer',
  cache: 'Served from cache',
};

// ---------------------------------------------------------------------------
// Defensive detail accessors — `detail` is free-form wire JSON.
// ---------------------------------------------------------------------------

function str(detail: Record<string, unknown>, key: string): string | null {
  const value = detail[key];
  return typeof value === 'string' ? value : null;
}

function num(detail: Record<string, unknown>, key: string): number | null {
  const value = detail[key];
  return typeof value === 'number' ? value : null;
}

function bool(detail: Record<string, unknown>, key: string): boolean {
  return detail[key] === true;
}

/** Read a key as a list of plain objects, or `[]` for any other shape. */
function objList(
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
function fieldStr(item: Record<string, unknown>, key: string): string | null {
  const value = item[key];
  return typeof value === 'string' ? value : null;
}

/** Read a key off a plain object as a number, or null. */
function fieldNum(item: Record<string, unknown>, key: string): number | null {
  const value = item[key];
  return typeof value === 'number' ? value : null;
}

/** Read a key off a plain object as a list of strings, dropping non-strings. */
function fieldStrList(item: Record<string, unknown>, key: string): string[] {
  const value = item[key];
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((entry): entry is string => typeof entry === 'string');
}

/** Read a key off a plain object as a list of numbers, dropping non-numbers. */
function fieldNumList(item: Record<string, unknown>, key: string): number[] {
  const value = item[key];
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((entry): entry is number => typeof entry === 'number');
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

// ---------------------------------------------------------------------------
// Token / cost formatting
// ---------------------------------------------------------------------------

/** Compact a token count: 1234 → "1.2k", 980 → "980", 12000 → "12k". */
export function compactTokens(total: number): string {
  if (total < 1000) {
    return String(total);
  }
  const thousands = total / 1000;
  // One decimal below 10k (1.2k), none above (12k) — keeps the chip short.
  const text =
    thousands < 10 ? thousands.toFixed(1) : String(Math.round(thousands));
  return `${text.replace(/\.0$/, '')}k`;
}

/** Format a dollar cost: $0 for zero, a precise small figure otherwise. */
export function formatUsd(usd: number): string {
  if (usd === 0) {
    return '$0';
  }
  if (usd >= 1) {
    return `$${usd.toFixed(2)}`;
  }
  // Sub-dollar: up to 4 decimals, trailing zeros trimmed (0.0040 → "$0.004").
  const trimmed = usd.toFixed(4).replace(/0+$/, '').replace(/\.$/, '');
  // A positive cost that rounds to $0.0000 still gets an honest floor.
  return trimmed === '0' ? '<$0.0001' : `$${trimmed}`;
}

/**
 * A compact "tokens · cost" label for an LLM phase, or undefined for a non-LLM
 * phase (which carries no tokens). Local provider → "$0"; unpriced usd → "—".
 */
export function formatCostLabel(
  tokens: TokenUsage | null,
  cost: Cost | null,
): string | undefined {
  if (tokens === null) {
    return undefined;
  }
  const tokensPart = `${compactTokens(tokens.total)} tok`;
  let costPart: string;
  if (cost === null) {
    costPart = '—';
  } else if (cost.local) {
    costPart = '$0';
  } else if (cost.usd === null) {
    costPart = '—';
  } else {
    costPart = formatUsd(cost.usd);
  }
  return `${tokensPart} · ${costPart}`;
}

/**
 * The whole-query "tokens · cost" label from a `CostSummary` (the answer-card
 * footer and the trace-panel summary). Shows "$0" for an all-local query and
 * "—" when the spend cannot be honestly priced; returns undefined when no LLM
 * call was made (zero tokens AND zero calls — nothing worth showing).
 */
export function formatSummaryCostLabel(
  summary: CostSummary,
): string | undefined {
  if (summary.tokens.total === 0 && summary.llm_calls === 0) {
    return undefined;
  }
  return formatCostLabel(summary.tokens, {
    usd: summary.usd,
    local: summary.local,
  });
}

// ---------------------------------------------------------------------------
// Planner / resolve / refine detail rendering
// ---------------------------------------------------------------------------

/**
 * Render an ordered list of short text lines as a stacked block. Each line is
 * its own block-level span so the lines stack vertically inside the row's
 * caption-styled `.detail` slot. Returns null for an empty list so the caller
 * can fall back.
 */
function lines(items: React.ReactNode[]): React.ReactNode {
  if (items.length === 0) {
    return null;
  }
  return (
    <>
      {items.map((item, i) => (
        <span key={i} className={styles['line']}>
          {item}
        </span>
      ))}
    </>
  );
}

/**
 * Summarise one planned spec's free-text filter guesses as a compact, readable
 * suffix (e.g. "from Npower · type Invoice · tags A, B · 2024-01-01→2024-12-31").
 * Returns the empty string when the spec carried no filter guesses.
 */
function planSpecFilters(spec: Record<string, unknown>): string {
  const filters = (spec['filters'] ?? {}) as Record<string, unknown>;
  const parts: string[] = [];
  const correspondent = fieldStr(filters, 'correspondent');
  if (correspondent !== null) {
    parts.push(`from ${correspondent}`);
  }
  const documentType = fieldStr(filters, 'document_type');
  if (documentType !== null) {
    parts.push(`type ${documentType}`);
  }
  const tags = fieldStrList(filters, 'tags');
  if (tags.length > 0) {
    parts.push(`tags ${tags.join(', ')}`);
  }
  const dateRange = formatDateRange(
    fieldStr(filters, 'date_from'),
    fieldStr(filters, 'date_to'),
  );
  if (dateRange !== null) {
    parts.push(dateRange);
  }
  return parts.join(' · ');
}

/** Format an inclusive ISO date range, or a single bound, or null when absent. */
function formatDateRange(from: string | null, to: string | null): string | null {
  if (from !== null && to !== null) {
    return `${from}→${to}`;
  }
  if (from !== null) {
    return `from ${from}`;
  }
  if (to !== null) {
    return `to ${to}`;
  }
  return null;
}

/**
 * Render the planner's per-spec search list (the `specs` detail key). One line
 * per planned search: its query text, its mode, the filter guesses, and the
 * planner's rationale. Falls back to the legacy `rewritten_query` rendering
 * when no specs are present (an older backend or a clarify outcome).
 */
function planNode(d: Record<string, unknown>): React.ReactNode {
  if (bool(d, 'skipped_trivial')) {
    return 'Trivial query — planning skipped';
  }
  const specs = objList(d, 'specs');
  if (specs.length === 0) {
    const rewritten = str(d, 'rewritten_query');
    return rewritten ? `Rewritten: “${rewritten}”` : null;
  }
  const rows = specs.map((spec, i): React.ReactNode => {
    const query = fieldStr(spec, 'query') ?? '';
    const mode = fieldStr(spec, 'mode');
    const filters = planSpecFilters(spec);
    const rationale = fieldStr(spec, 'rationale');
    const head = `${i + 1}. “${query}”${mode !== null ? ` (${mode})` : ''}`;
    const tail = [filters, rationale ? `— ${rationale}` : '']
      .filter((part) => part !== '')
      .join(' · ');
    return tail !== '' ? `${head} · ${tail}` : head;
  });
  return lines(rows);
}

/**
 * Render the resolve phase: per-spec resolved taxonomy ids / date bounds and
 * the guesses that did not resolve to a real id. The detail carries `resolved`
 * (a list with ids and ISO dates) and `dropped` (per-spec dropped name lists).
 */
function resolveNode(d: Record<string, unknown>): React.ReactNode {
  const resolved = objList(d, 'resolved');
  const dropped = objList(d, 'dropped');
  if (resolved.length === 0 && dropped.length === 0) {
    return null;
  }
  const rows: React.ReactNode[] = resolved.map((spec, i): React.ReactNode => {
    const bits: string[] = [];
    const correspondentId = fieldNum(spec, 'correspondent_id');
    if (correspondentId !== null) {
      bits.push(`correspondent #${correspondentId}`);
    }
    const documentTypeId = fieldNum(spec, 'document_type_id');
    if (documentTypeId !== null) {
      bits.push(`type #${documentTypeId}`);
    }
    const tagIds = fieldNumList(spec, 'tag_ids');
    if (tagIds.length > 0) {
      bits.push(`tags ${tagIds.map((id) => `#${id}`).join(', ')}`);
    }
    const dateRange = formatDateRange(
      fieldStr(spec, 'date_from'),
      fieldStr(spec, 'date_to'),
    );
    if (dateRange !== null) {
      bits.push(`date ${dateRange}`);
    }
    const index = fieldNum(spec, 'spec_index') ?? i;
    const body = bits.length > 0 ? bits.join(' · ') : 'no filters';
    return `${index + 1}. ${body}`;
  });

  const droppedNames = dropped.flatMap((entry) => fieldStrList(entry, 'names'));
  if (droppedNames.length > 0) {
    rows.push(`Dropped (no match): ${droppedNames.join(', ')}`);
  }
  return lines(rows);
}

/**
 * Render the refine phase: the synthesiser's gap hint, the action taken, the
 * new searches the re-plan added (or none on a no-op), and how many documents
 * carried over from the previous round.
 */
function refineNode(d: Record<string, unknown>): React.ReactNode {
  const gap = str(d, 'gap');
  const action = str(d, 'action');
  const carriedOver = num(d, 'carried_over');
  const newSpecs = objList(d, 'new_specs');
  const noop = bool(d, 'noop');

  const rows: React.ReactNode[] = [];
  if (gap !== null) {
    rows.push(`Gap: ${gap}`);
  }
  if (action !== null) {
    rows.push(`Action: ${action}`);
  }
  if (!noop) {
    newSpecs.forEach((spec, i) => {
      const query = fieldStr(spec, 'query') ?? '';
      const mode = fieldStr(spec, 'mode');
      rows.push(
        `New search ${i + 1}: “${query}”${mode !== null ? ` (${mode})` : ''}`,
      );
    });
  }
  if (carriedOver !== null) {
    rows.push(`Carried over ${carriedOver} document${carriedOver === 1 ? '' : 's'}`);
  }
  return lines(rows);
}

/**
 * Render the replan phase: the gap hint that drove the re-plan and the new
 * searches it produced (or a note that it asked to clarify, which refinement
 * ignores).
 */
function replanNode(d: Record<string, unknown>): React.ReactNode {
  if (bool(d, 'clarify')) {
    return 'Re-plan asked to clarify — ignored, finalising on current evidence';
  }
  const hint = str(d, 'hint');
  const specs = objList(d, 'specs');
  const rows: React.ReactNode[] = [];
  if (hint !== null) {
    rows.push(`Hint: ${hint}`);
  }
  specs.forEach((spec, i) => {
    const query = fieldStr(spec, 'query') ?? '';
    const mode = fieldStr(spec, 'mode');
    rows.push(`${i + 1}. “${query}”${mode !== null ? ` (${mode})` : ''}`);
  });
  return lines(rows);
}

// ---------------------------------------------------------------------------
// Per-phase one-line summary (the always-visible row text)
// ---------------------------------------------------------------------------

/** Pluralise a noun by count: 1 → "1 chunk", 2 → "2 chunks". Handles the
 *  "-ch → -ches" case (search → searches) used by the planner summary. */
function plural(count: number, noun: string): string {
  if (count === 1) {
    return `${count} ${noun}`;
  }
  const suffix = noun.endsWith('ch') ? 'es' : 's';
  return `${count} ${noun}${suffix}`;
}

/** Does one resolved spec carry at least one real, resolved filter? Tolerates
 *  both the new object wire ({correspondent: {id,name,method}}) and the legacy
 *  id wire ({correspondent_id: 7}). */
function specHasResolvedFilter(spec: Record<string, unknown>): boolean {
  const hasObj =
    spec['correspondent'] != null ||
    spec['document_type'] != null ||
    objList(spec, 'tags').length > 0;
  const hasLegacy =
    fieldNum(spec, 'correspondent_id') !== null ||
    fieldNum(spec, 'document_type_id') !== null ||
    fieldNumList(spec, 'tag_ids').length > 0;
  const dateRange = formatDateRange(
    fieldStr(spec, 'date_from'),
    fieldStr(spec, 'date_to'),
  );
  return hasObj || hasLegacy || dateRange !== null;
}

/**
 * The one-line summary for a phase — the always-visible row text in the
 * collapsible trace and the only text shown in the lean live rail. Each phase
 * compresses its outcome to a single readable line; phases without a bespoke
 * summary fall back to `phaseDetailNode`.
 */
export function phaseSummary(record: PhaseRecord): React.ReactNode {
  const d = record.detail;
  switch (record.phase) {
    case 'plan': {
      if (bool(d, 'skipped_trivial')) {
        return 'Trivial query — planning skipped';
      }
      const specs = objList(d, 'specs');
      if (specs.length === 0) {
        // Older shape / clarify: fall back to the legacy rewritten-query line.
        return phaseDetailNode(record);
      }
      let keyword = 0;
      let semantic = 0;
      specs.forEach((spec) => {
        const mode = fieldStr(spec, 'mode');
        if (mode === 'keyword') {
          keyword += 1;
        } else {
          semantic += 1;
        }
      });
      const modeBits: string[] = [];
      if (keyword > 0) {
        modeBits.push(`${keyword} keyword`);
      }
      if (semantic > 0) {
        modeBits.push(`${semantic} semantic`);
      }
      const head = plural(specs.length, 'search') + ' planned';
      return modeBits.length > 0 ? `${head} · ${modeBits.join(', ')}` : head;
    }
    case 'resolve': {
      const resolved = objList(d, 'resolved');
      const dropped = objList(d, 'dropped');
      const resolvedCount = resolved.filter(specHasResolvedFilter).length;
      const droppedCount = dropped.length;
      return (
        <span className={styles['accent']}>
          {plural(resolvedCount, 'filter')} resolved · {droppedCount} dropped
        </span>
      );
    }
    case 'retrieve': {
      const chunks = num(d, 'chunk_count') ?? 0;
      const docs = num(d, 'doc_count') ?? 0;
      return `${plural(chunks, 'chunk')} · ${plural(docs, 'document')}`;
    }
    case 'gate': {
      if (bool(d, 'rejected')) {
        return 'Rejected — retrieval too weak';
      }
      const evaluated = num(d, 'evaluated') ?? 0;
      const best = num(d, 'best_similarity');
      const bestText = best !== null ? ` · best ${best.toFixed(2)}` : '';
      return `Passed ${plural(evaluated, 'document')}${bestText}`;
    }
    case 'judge':
      return phaseDetailNode(record);
    default:
      return phaseDetailNode(record);
  }
}

// ---------------------------------------------------------------------------
// Per-phase expandable body nodes (the rich detail shown when expanded)
// ---------------------------------------------------------------------------

/** Read a nested object field as a plain record, or null for any other shape. */
function fieldObj(
  item: Record<string, unknown>,
  key: string,
): Record<string, unknown> | null {
  const value = item[key];
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

/**
 * Render the resolve phase body with the new object wire shape — each resolved
 * spec carries `{correspondent, document_type, tags}` objects with `{id, name,
 * method}` (or null). A `method === 'loose'` field is annotated as loosened
 * from the planner's original guess (read from the threaded plan specs).
 * Tolerates the legacy id wire shape (falls back to `#id`).
 */
function resolveBodyNode(
  d: Record<string, unknown>,
  planSpecs: Record<string, unknown>[] = [],
): React.ReactNode {
  const resolved = objList(d, 'resolved');
  const dropped = objList(d, 'dropped');
  if (resolved.length === 0 && dropped.length === 0) {
    return null;
  }

  /** The planner's free-text guess for a field on the spec at `index`. */
  function guessFor(index: number, key: string): string | null {
    const planSpec = planSpecs[index];
    if (planSpec === undefined) {
      return null;
    }
    const filters = (planSpec['filters'] ?? {}) as Record<string, unknown>;
    return fieldStr(filters, key);
  }

  const rows: React.ReactNode[] = resolved.map((spec, i): React.ReactNode => {
    const index = fieldNum(spec, 'spec_index') ?? i;
    const bits: React.ReactNode[] = [];

    /** Render one resolved taxonomy field (correspondent / document_type). */
    function renderField(
      key: string,
      verb: string,
      guessKey: string,
    ): void {
      const obj = fieldObj(spec, key);
      if (obj !== null) {
        const name = fieldStr(obj, 'name');
        const method = fieldStr(obj, 'method');
        if (name !== null) {
          const loose = method === 'loose';
          const guess = loose ? guessFor(index, guessKey) : null;
          bits.push(
            <React.Fragment key={`${key}-${bits.length}`}>
              {`${verb} ${name}`}
              {loose && (
                <span className={styles['loosened']}>
                  {guess !== null
                    ? ` · loosened from “${guess}”`
                    : ' · loosened'}
                </span>
              )}
            </React.Fragment>,
          );
          return;
        }
      }
      // Legacy id wire fallback.
      const legacyId = fieldNum(spec, `${key}_id`);
      if (legacyId !== null) {
        bits.push(`${verb} #${legacyId}`);
      }
    }

    renderField('correspondent', 'from', 'correspondent');
    renderField('document_type', 'type', 'document_type');

    // Tags — new object wire, with a legacy id-list fallback.
    const tagObjs = objList(spec, 'tags');
    if (tagObjs.length > 0) {
      const tagBits: React.ReactNode[] = tagObjs.map((tag, ti) => {
        const name = fieldStr(tag, 'name');
        const method = fieldStr(tag, 'method');
        const loose = method === 'loose';
        return (
          <React.Fragment key={ti}>
            {ti > 0 ? ', ' : ''}
            {name ?? '?'}
            {loose && <span className={styles['loosened']}> · loosened</span>}
          </React.Fragment>
        );
      });
      bits.push(
        <React.Fragment key={`tags-${bits.length}`}>
          {'tags '}
          {tagBits}
        </React.Fragment>,
      );
    } else {
      const tagIds = fieldNumList(spec, 'tag_ids');
      if (tagIds.length > 0) {
        bits.push(`tags ${tagIds.map((id) => `#${id}`).join(', ')}`);
      }
    }

    const dateRange = formatDateRange(
      fieldStr(spec, 'date_from'),
      fieldStr(spec, 'date_to'),
    );
    if (dateRange !== null) {
      bits.push(`date ${dateRange}`);
    }

    return (
      <>
        {`${index + 1}. `}
        {bits.length > 0
          ? bits.map((bit, bi) => (
              <React.Fragment key={bi}>
                {bi > 0 ? ' · ' : ''}
                {bit}
              </React.Fragment>
            ))
          : 'no filters proposed'}
      </>
    );
  });

  dropped.forEach((entry, i) => {
    const name = fieldStr(entry, 'name');
    if (name !== null) {
      const reason = fieldStr(entry, 'reason');
      const candidates = fieldStrList(entry, 'candidates');
      if (reason === 'ambiguous' && candidates.length > 0) {
        rows.push(
          <React.Fragment key={`drop-${i}`}>
            {`Dropped (ambiguous): ${name} → ${candidates.join(', ')}`}
          </React.Fragment>,
        );
      } else {
        rows.push(
          <React.Fragment key={`drop-${i}`}>
            {`Dropped (no match): ${name}`}
          </React.Fragment>,
        );
      }
    } else {
      // Legacy dropped wire: {spec_index, names: [...]}.
      const names = fieldStrList(entry, 'names');
      if (names.length > 0) {
        rows.push(
          <React.Fragment key={`drop-${i}`}>
            {`Dropped (no match): ${names.join(', ')}`}
          </React.Fragment>,
        );
      }
    }
  });

  return lines(rows);
}

/**
 * Render the retrieve phase body — one subrow per retrieved chunk: a dot, the
 * document title with a monospace similarity-score prefix, and the snippet as
 * a focusable `.chunk-snip` element carrying the full text in data-attributes
 * for the shared ChunkPopover.
 */
function retrieveBodyNode(d: Record<string, unknown>): React.ReactNode {
  const chunks = objList(d, 'chunks');
  if (chunks.length === 0) {
    return null;
  }
  return (
    <div className={styles['sublist']}>
      {chunks.map((chunk, i) => {
        const title = fieldStr(chunk, 'title') ?? `Document ${fieldNum(chunk, 'document_id') ?? '?'}`;
        const snippet = fieldStr(chunk, 'snippet') ?? '';
        const sim = fieldNum(chunk, 'vector_similarity');
        const scoreText = sim !== null ? sim.toFixed(2) : '';
        return (
          <div key={i} className={styles['subrow']}>
            <span className={styles['sdot']} aria-hidden="true" />
            <span className={styles['stext']}>
              <span className={styles['stitle']}>
                {scoreText !== '' && (
                  <span className={styles['score']}>{scoreText}</span>
                )}
                {title}
              </span>
              {snippet !== '' && (
                <span
                  className={styles['chunk-snip']}
                  tabIndex={0}
                  data-title={title}
                  data-score={scoreText}
                  data-full={snippet}
                >
                  {snippet}
                </span>
              )}
            </span>
          </div>
        );
      })}
    </div>
  );
}

/**
 * Render the gate phase body — one subrow per evaluated document: a dot, the
 * title, and a similarity bar whose fill width tracks the best vector
 * similarity for that document.
 */
function gateBodyNode(d: Record<string, unknown>): React.ReactNode {
  const documents = objList(d, 'documents');
  if (documents.length === 0) {
    return null;
  }
  return (
    <div className={styles['sublist']}>
      {documents.map((doc, i) => {
        const title = fieldStr(doc, 'title') ?? `Document ${fieldNum(doc, 'document_id') ?? '?'}`;
        const sim = fieldNum(doc, 'best_similarity');
        const pct = Math.round((sim ?? 0) * 100);
        const scoreText = sim !== null ? sim.toFixed(2) : '';
        return (
          <div key={i} className={styles['subrow']}>
            <span className={styles['sdot']} aria-hidden="true" />
            <span className={styles['stext']}>
              <span className={styles['stitle']}>
                {scoreText !== '' && (
                  <span className={styles['score']}>{scoreText}</span>
                )}
                {title}
              </span>
              <div className={styles['bar']}>
                <i style={{ width: `${pct}%` } as React.CSSProperties} />
              </div>
            </span>
          </div>
        );
      })}
    </div>
  );
}

/**
 * The expandable body node for a phase, or null when the phase has nothing to
 * expand (its summary line carries everything). `planSpecs` threads the
 * planner's free-text guesses into the resolve body so loosened matches can
 * name what they loosened from.
 */
export function phaseBodyNode(
  record: PhaseRecord,
  planSpecs: Record<string, unknown>[] = [],
): React.ReactNode {
  const d = record.detail;
  switch (record.phase) {
    case 'plan':
      return planNode(d);
    case 'resolve':
      return resolveBodyNode(d, planSpecs);
    case 'retrieve':
      return retrieveBodyNode(d);
    case 'gate':
      return gateBodyNode(d);
    case 'judge':
      // The judge's verdict list (with the View control) is rendered by
      // PipelineStages from the `verdicts` field, so there is no separate body.
      return null;
    default:
      // refine / replan / synthesise / cache carry their whole detail in the
      // summary line (via phaseDetailNode), so they have no separate body — a
      // duplicate body would render the same lines twice.
      return null;
  }
}

// ---------------------------------------------------------------------------
// Per-phase detail node
// ---------------------------------------------------------------------------

/**
 * The rich detail node for one phase, rendered under its label. Returns null
 * when there is nothing useful to show (the row then falls back to its plain
 * `detail` string, which is empty for live phases).
 */
export function phaseDetailNode(record: PhaseRecord): React.ReactNode {
  const d = record.detail;
  switch (record.phase) {
    case 'plan':
      return planNode(d);
    case 'resolve':
      return resolveNode(d);
    case 'retrieve': {
      const chunks = num(d, 'chunk_count');
      const docs = num(d, 'doc_count');
      if (chunks === null && docs === null) {
        return null;
      }
      const broadened = bool(d, 'broadened') ? ' · broadened' : '';
      return `${chunks ?? 0} chunks · ${docs ?? 0} documents${broadened}`;
    }
    case 'gate': {
      const evaluated = num(d, 'evaluated');
      if (bool(d, 'rejected')) {
        return 'Rejected — retrieval too weak';
      }
      const best = num(d, 'best_similarity');
      const bestText = best !== null ? ` · best ${best.toFixed(2)}` : '';
      return evaluated !== null
        ? `Passed ${evaluated} documents${bestText}`
        : null;
    }
    case 'judge': {
      const verdicts = verdictsOf(record) ?? [];
      const kept = verdicts.filter((v) => v.keep).length;
      const dropped = verdicts.length - kept;
      if (bool(d, 'degraded')) {
        return 'Judge unavailable — kept all (fail-open)';
      }
      if (bool(d, 'bailed')) {
        return 'No document judged relevant';
      }
      if (verdicts.length === 0) {
        return null;
      }
      return `Kept ${kept}, dropped ${dropped}`;
    }
    case 'synthesise': {
      const mode = str(d, 'mode');
      const needsMore = bool(d, 'needs_more') ? ' · needs more context' : '';
      return mode ? `Mode: ${mode}${needsMore}` : null;
    }
    case 'replan':
      return replanNode(d);
    case 'refine':
      return refineNode(d);
    case 'cache':
      return 'Answer served from the cache';
    default:
      return null;
  }
}

// ---------------------------------------------------------------------------
// Phase → stage mapping
// ---------------------------------------------------------------------------

/**
 * Map the streamed phases onto `PipelineStage[]` for the rail / trace panel.
 *
 * Each completed `PhaseRecord` becomes a `done` row with its detail node, cost
 * chip and (for judge) verdict sublist. When `activePhase` is set and has not
 * yet produced a record, a trailing `active` row is appended so the rail shows
 * the in-flight phase "in progress". Pass `activePhase = null` for a finished
 * trace (every row `done`).
 *
 * @param records     The completed phases, in order.
 * @param activePhase The phase currently running, or null.
 */
export function phaseToStages(
  records: PhaseRecord[],
  activePhase: SearchPhase | null,
): PipelineStage[] {
  // The planner's per-spec free-text guesses, threaded into the resolve body so
  // loosened taxonomy matches can name what they were loosened from.
  const planRecord = records.find((r) => r.phase === 'plan');
  const planSpecs =
    planRecord !== undefined ? objList(planRecord.detail, 'specs') : [];

  const stages: PipelineStage[] = records.map((record) => {
    const state: PipelineStageState = 'done';
    const detailNode = phaseDetailNode(record);
    const summary = phaseSummary(record);
    const body = phaseBodyNode(record, planSpecs);
    const costLabel = formatCostLabel(record.tokens, record.cost);
    const verdicts = verdictsOf(record);
    return {
      label: record.label,
      detail: '',
      state,
      ...(summary !== null ? { summary } : {}),
      ...(body !== null ? { body } : {}),
      ...(detailNode !== null ? { detailNode } : {}),
      ...(costLabel !== undefined ? { costLabel } : {}),
      ...(verdicts !== undefined ? { verdicts } : {}),
    };
  });

  // Append the in-flight phase as an active row when it has no record yet. The
  // last recorded phase can equal activePhase only transiently; the reducer
  // clears activePhase on phase_done, so a duplicate row cannot persist.
  if (activePhase !== null) {
    stages.push({
      label: PHASE_LABELS[activePhase],
      detail: '',
      state: 'active',
    });
  }

  return stages;
}
