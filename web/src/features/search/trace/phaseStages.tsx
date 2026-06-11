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
 * Return the ordinal suffix for a 1-based index: 1→"1st", 2→"2nd", 3→"3rd",
 * 4→"4th", …, 11→"11th", 12→"12th", 13→"13th", 21→"21st", etc.
 */
export function ordinal(n: number): string {
  const abs = Math.abs(n);
  const mod100 = abs % 100;
  // Special-case the teens (11–13) which break the normal suffix pattern.
  if (mod100 >= 11 && mod100 <= 13) {
    return `${n}th`;
  }
  const mod10 = abs % 10;
  if (mod10 === 1) return `${n}st`;
  if (mod10 === 2) return `${n}nd`;
  if (mod10 === 3) return `${n}rd`;
  return `${n}th`;
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
 * Render the planner's per-spec search list (the `specs` detail key).
 *
 * Each spec becomes a structured block containing:
 *   - a meta row: ordinal label, mode badge (Keyword/Semantic), filter chips
 *   - the query text in curly quotes on its own line
 *   - the rationale on its own line below (smaller, tertiary)
 *
 * Falls back to the legacy `rewritten_query` rendering when no specs are
 * present (an older backend or a clarify outcome).
 */
/** One filter chip — a dim key label ("from"/"type"/"tags") and its value. */
function filterChip(key: string, label: string, value: string): React.ReactNode {
  return (
    <span key={key} className={styles['qfilter']}>
      <span className={styles['qfilter-key']}>{label} </span>
      {value}
    </span>
  );
}

/**
 * Build the filter chips for one query block. Reads either the planner's
 * free-text guesses (`correspondent`/`document_type`/`tags` strings — plan and
 * replan) or resolved taxonomy ids (`correspondent_id`/… — refine); the two
 * shapes are disjoint, so the same renderer serves all three phases.
 */
function filterChips(filters: Record<string, unknown>): React.ReactNode[] {
  const chips: React.ReactNode[] = [];
  const correspondent = fieldStr(filters, 'correspondent');
  if (correspondent !== null) {
    chips.push(filterChip('correspondent', 'from', correspondent));
  }
  const documentType = fieldStr(filters, 'document_type');
  if (documentType !== null) {
    chips.push(filterChip('document_type', 'type', documentType));
  }
  const tags = fieldStrList(filters, 'tags');
  if (tags.length > 0) {
    chips.push(filterChip('tags', 'tags', tags.join(', ')));
  }
  const correspondentId = fieldNum(filters, 'correspondent_id');
  if (correspondentId !== null) {
    chips.push(filterChip('correspondent_id', 'from', `#${correspondentId}`));
  }
  const documentTypeId = fieldNum(filters, 'document_type_id');
  if (documentTypeId !== null) {
    chips.push(filterChip('document_type_id', 'type', `#${documentTypeId}`));
  }
  const tagIds = fieldNumList(filters, 'tag_ids');
  if (tagIds.length > 0) {
    chips.push(
      filterChip('tag_ids', 'tags', tagIds.map((id) => `#${id}`).join(', ')),
    );
  }
  const dateRange = formatDateRange(
    fieldStr(filters, 'date_from'),
    fieldStr(filters, 'date_to'),
  );
  if (dateRange !== null) {
    chips.push(
      <span key="date" className={styles['qfilter']}>
        {dateRange}
      </span>,
    );
  }
  return chips;
}

/**
 * Render a list of search specs as styled query blocks — ordinal label, mode
 * badge, filter chips, the query in curly quotes, and the rationale beneath.
 * Shared by the plan, replan and refine phases so all three look identical.
 */
function queryBlocksNode(specs: Record<string, unknown>[]): React.ReactNode {
  const blocks = specs.map((spec, i): React.ReactNode => {
    const query = fieldStr(spec, 'query') ?? '';
    const mode = fieldStr(spec, 'mode');
    const rationale = fieldStr(spec, 'rationale');
    const filters = (spec['filters'] ?? {}) as Record<string, unknown>;

    const isKeyword = mode === 'keyword';
    const modeClass = isKeyword ? styles['qmode-keyword'] : styles['qmode-semantic'];
    const modeLabel = isKeyword ? 'Keyword' : 'Semantic';

    return (
      <div key={i} className={styles['qblock']}>
        <div className={styles['qmeta']}>
          <span className={styles['qord']}>{ordinal(i + 1)} query</span>
          {mode !== null && (
            <span className={`${styles['qmode']} ${modeClass}`}>{modeLabel}</span>
          )}
          {filterChips(filters)}
        </div>
        <div className={styles['qtext']}>{'“'}{query}{'”'}</div>
        {rationale !== null && rationale !== '' && (
          <div className={styles['qwhy']}>{rationale}</div>
        )}
      </div>
    );
  });

  return <>{blocks}</>;
}

/** A context line above a re-plan / refine query list — an optional dim key
 *  ("Gap", "Action") followed by the value, styled to match the trace body. */
function hintLine(key: string | null, value: string): React.ReactNode {
  return (
    <div className={styles['qhint']}>
      {key !== null && <span className={styles['qhint-key']}>{key} </span>}
      {value}
    </div>
  );
}

function planNode(d: Record<string, unknown>): React.ReactNode {
  if (bool(d, 'skipped_trivial')) {
    return 'Trivial query — planning skipped';
  }
  const specs = objList(d, 'specs');
  if (specs.length === 0) {
    const rewritten = str(d, 'rewritten_query');
    return rewritten ? `Rewritten: "${rewritten}"` : null;
  }
  return queryBlocksNode(specs);
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
 * Render the refine phase body: the synthesiser's gap, the action taken, the
 * new searches the re-plan added (as styled query blocks), and how many
 * documents carried over — matching the planning phase's styling.
 */
function refineBodyNode(d: Record<string, unknown>): React.ReactNode {
  const gap = str(d, 'gap');
  const action = str(d, 'action');
  const carriedOver = num(d, 'carried_over');
  const newSpecs = objList(d, 'new_specs');
  return (
    <>
      {gap !== null && hintLine('Gap', gap)}
      {action !== null && hintLine('Action', action)}
      {newSpecs.length > 0 && queryBlocksNode(newSpecs)}
      {carriedOver !== null &&
        hintLine('Carried over', plural(carriedOver, 'document'))}
    </>
  );
}

/**
 * Render the replan phase body: the gap hint that drove the re-plan and the new
 * searches it produced as styled query blocks (matching the planning phase), or
 * a note that it asked to clarify (which refinement ignores).
 */
function replanBodyNode(d: Record<string, unknown>): React.ReactNode {
  if (bool(d, 'clarify')) {
    return hintLine(
      null,
      'Re-plan asked to clarify — finalising on current evidence',
    );
  }
  const hint = str(d, 'hint');
  const specs = objList(d, 'specs');
  return (
    <>
      {hint !== null && hintLine('Gap', hint)}
      {specs.length > 0 && queryBlocksNode(specs)}
    </>
  );
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
 * "<head> · K keyword, S semantic" — the count summary shared by the plan and
 * replan phases. `head` carries the accent-styled lead ("3 searches planned",
 * "2 searches re-planned"); the keyword/semantic tail is appended plainly.
 */
function searchModeSummary(
  specs: Record<string, unknown>[],
  head: string,
): React.ReactNode {
  let keyword = 0;
  let semantic = 0;
  specs.forEach((spec) => {
    if (fieldStr(spec, 'mode') === 'keyword') {
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
  return (
    <>
      <span className={styles['accent']}>{head}</span>
      {modeBits.length > 0 ? ` · ${modeBits.join(', ')}` : ''}
    </>
  );
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
      return searchModeSummary(specs, plural(specs.length, 'search') + ' planned');
    }
    case 'replan': {
      if (bool(d, 'clarify')) {
        return 'Asked to clarify — finalising on current evidence';
      }
      const specs = objList(d, 'specs');
      if (specs.length === 0) {
        return 'Re-planned';
      }
      return searchModeSummary(
        specs,
        plural(specs.length, 'search') + ' re-planned',
      );
    }
    case 'refine': {
      if (bool(d, 'noop')) {
        return 'No new searches — finalising on current evidence';
      }
      const newSpecs = objList(d, 'new_specs');
      const carried = num(d, 'carried_over');
      const carriedText =
        carried !== null ? ` · ${plural(carried, 'document')} carried over` : '';
      return (
        <>
          <span className={styles['accent']}>
            {plural(newSpecs.length, 'search') + ' added'}
          </span>
          {carriedText}
        </>
      );
    }
    case 'resolve': {
      const resolved = objList(d, 'resolved');
      const dropped = objList(d, 'dropped');
      const resolvedCount = resolved.filter(specHasResolvedFilter).length;
      const droppedCount = dropped.length;
      return (
        <>
          <span className={styles['accent']}>{resolvedCount} kept</span>
          {` · ${droppedCount} dropped`}
        </>
      );
    }
    case 'retrieve': {
      const chunks = num(d, 'chunk_count') ?? 0;
      const docs = num(d, 'doc_count') ?? 0;
      return (
        <>
          <span className={styles['accent']}>{plural(chunks, 'chunk')}</span>
          {` · ${plural(docs, 'document')}`}
        </>
      );
    }
    case 'gate': {
      if (bool(d, 'rejected')) {
        return 'Rejected — retrieval too weak';
      }
      const evaluated = num(d, 'evaluated') ?? 0;
      const best = num(d, 'best_similarity');
      const bestText = best !== null ? ` · best ${best.toFixed(2)}` : '';
      return (
        <>
          <span className={styles['accent']}>
            Passed {plural(evaluated, 'document')}
          </span>
          {bestText}
        </>
      );
    }
    case 'judge': {
      // Wrap the judge's headline ("No document judged relevant" / "Kept K,
      // dropped D") in the same quiet emphasis as the other phase summaries.
      const node = phaseDetailNode(record);
      return typeof node === 'string' ? (
        <span className={styles['accent']}>{node}</span>
      ) : (
        node
      );
    }
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

// Short chip label per resolved/dropped filter dimension — matches the verbs
// used by the planning step's chips ("from"/"type"/"tags").
const RESOLVE_DIM_LABEL: Record<string, string> = {
  correspondent: 'from',
  document_type: 'type',
  tags: 'tags',
};

// Human noun per dimension, for the "no matching …" drop reason.
const RESOLVE_DIM_NOUN: Record<string, string> = {
  correspondent: 'correspondent',
  document_type: 'document type',
  tags: 'tag',
};

/**
 * One "kept" filter row: a ✓ mark, a neutral chip (dimension + value), and an
 * optional muted annotation (e.g. `loosened from "Deed"`). The mark is
 * decorative — the outcome is also carried by the chip styling and annotation.
 */
function keptFilterRow(
  key: string,
  dim: string | null,
  value: React.ReactNode,
  annot?: React.ReactNode,
): React.ReactNode {
  return (
    <div key={key} className={styles['frow']}>
      <span
        className={`${styles['mark']} ${styles['mark-kept']}`}
        aria-hidden="true"
      >
        ✓
      </span>
      <span className={styles['fchip']}>
        {dim !== null && <span className={styles['dim']}>{dim}</span>}
        <span className={styles['val']}>{value}</span>
      </span>
      {annot !== undefined && <span className={styles['annot']}>{annot}</span>}
    </div>
  );
}

/**
 * One "dropped" filter row: a ✕ mark, a dashed chip with the struck-through
 * value, and the drop reason. Keeps the filter visible under its query rather
 * than hiding it in a query-less list.
 */
function droppedFilterRow(
  key: string,
  dim: string | null,
  value: React.ReactNode,
  annot: React.ReactNode,
): React.ReactNode {
  return (
    <div key={key} className={styles['frow']}>
      <span
        className={`${styles['mark']} ${styles['mark-drop']}`}
        aria-hidden="true"
      >
        ✕
      </span>
      <span className={`${styles['fchip']} ${styles['fchip-dropped']}`}>
        {dim !== null && <span className={styles['dim']}>{dim}</span>}
        <span className={styles['val']}>{value}</span>
      </span>
      <span className={`${styles['annot']} ${styles['annot-drop']}`}>{annot}</span>
    </div>
  );
}

/**
 * Render the resolve phase body as one block per planned query, mirroring the
 * planning step. Each block lists *all* of that query's filters as status chips:
 * kept (✓), loosened (✓ + `loosened from "…"`), or dropped (✕, struck chip +
 * the reason it could not be matched). A query that proposed nothing shows
 * "No filters proposed".
 *
 * Dropped guesses are grouped under the query that proposed them via their
 * `spec_index`; an older trace whose drops lack a `spec_index` falls back to a
 * trailing "Dropped" block so a drop is never silently hidden.
 *
 * Supports both the new object wire (`{correspondent, document_type, tags}`
 * with `{id, name, method}`) and the legacy id wire (falls back to `#id`).
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

  /** The planner's free-text guess for a filter key on the spec at `index`. */
  function guessFor(index: number, key: string): string | null {
    const planSpec = planSpecs[index];
    if (planSpec === undefined) {
      return null;
    }
    const filters = (planSpec['filters'] ?? {}) as Record<string, unknown>;
    return fieldStr(filters, key);
  }

  // Index resolved specs by their query position (fallback to array order).
  const resolvedByIndex = new Map<number, Record<string, unknown>>();
  resolved.forEach((spec, i) => {
    resolvedByIndex.set(fieldNum(spec, 'spec_index') ?? i, spec);
  });

  // Group dropped guesses by the query that proposed them; drops without a
  // spec_index (older traces) collect into a trailing block.
  const droppedByIndex = new Map<number, Record<string, unknown>[]>();
  const orphanDrops: Record<string, unknown>[] = [];
  dropped.forEach((entry) => {
    const idx = fieldNum(entry, 'spec_index');
    if (idx === null) {
      orphanDrops.push(entry);
      return;
    }
    const bucket = droppedByIndex.get(idx) ?? [];
    bucket.push(entry);
    droppedByIndex.set(idx, bucket);
  });

  /** Kept rows for one resolved spec, across every filter dimension. */
  function keptRowsFor(
    spec: Record<string, unknown>,
    index: number,
  ): React.ReactNode[] {
    const rows: React.ReactNode[] = [];

    function renderField(key: string, dim: string, guessKey: string): void {
      const obj = fieldObj(spec, key);
      if (obj !== null) {
        const name = fieldStr(obj, 'name');
        if (name !== null) {
          const loose = fieldStr(obj, 'method') === 'loose';
          const guess = loose ? guessFor(index, guessKey) : null;
          const annot = loose
            ? guess !== null
              ? `loosened from "${guess}"`
              : 'loosened'
            : undefined;
          rows.push(keptFilterRow(`${key}-${index}`, dim, name, annot));
          return;
        }
      }
      // Legacy id wire fallback.
      const legacyId = fieldNum(spec, `${key}_id`);
      if (legacyId !== null) {
        rows.push(keptFilterRow(`${key}-${index}`, dim, `#${legacyId}`));
      }
    }

    renderField('correspondent', 'from', 'correspondent');
    renderField('document_type', 'type', 'document_type');

    // Tags — new object wire (one row per tag), with a legacy id-list fallback.
    const tagObjs = objList(spec, 'tags');
    if (tagObjs.length > 0) {
      tagObjs.forEach((tag, ti) => {
        const name = fieldStr(tag, 'name') ?? '?';
        const loose = fieldStr(tag, 'method') === 'loose';
        rows.push(
          keptFilterRow(
            `tag-${index}-${ti}`,
            'tags',
            name,
            loose ? 'loosened' : undefined,
          ),
        );
      });
    } else {
      fieldNumList(spec, 'tag_ids').forEach((id, ti) => {
        rows.push(keptFilterRow(`tagid-${index}-${ti}`, 'tags', `#${id}`));
      });
    }

    const dateRange = formatDateRange(
      fieldStr(spec, 'date_from'),
      fieldStr(spec, 'date_to'),
    );
    if (dateRange !== null) {
      rows.push(keptFilterRow(`date-${index}`, 'date', dateRange));
    }
    return rows;
  }

  /** Dropped rows for one query's dropped guesses. */
  function droppedRowsFor(
    entries: Record<string, unknown>[],
    index: number,
  ): React.ReactNode[] {
    const rows: React.ReactNode[] = [];
    entries.forEach((entry, di) => {
      const name = fieldStr(entry, 'name');
      if (name !== null) {
        const fieldKind = fieldStr(entry, 'field');
        const dim = fieldKind !== null ? RESOLVE_DIM_LABEL[fieldKind] ?? null : null;
        const noun =
          fieldKind !== null ? RESOLVE_DIM_NOUN[fieldKind] ?? 'filter' : 'filter';
        const candidates = fieldStrList(entry, 'candidates');
        const reason = fieldStr(entry, 'reason');
        const annot =
          reason === 'ambiguous' && candidates.length > 0
            ? `ambiguous — matched ${candidates.join(', ')}`
            : reason === 'near_miss' && candidates.length > 0
              ? `no match — nearest ${candidates.join(', ')}`
              : `no matching ${noun}`;
        rows.push(droppedFilterRow(`drop-${index}-${di}`, dim, name, annot));
        return;
      }
      // Legacy dropped wire: {spec_index, names: [...]} — no field or reason.
      fieldStrList(entry, 'names').forEach((nm, ni) => {
        rows.push(
          droppedFilterRow(`dropn-${index}-${di}-${ni}`, null, nm, 'no match'),
        );
      });
    });
    return rows;
  }

  // Total query count: trust the planner's spec list; fall back to the highest
  // index seen in the data when plan specs were not threaded in.
  const dataMax = Math.max(
    -1,
    ...resolvedByIndex.keys(),
    ...droppedByIndex.keys(),
  );
  const total = Math.max(planSpecs.length, dataMax + 1);

  const blocks: React.ReactNode[] = Array.from({ length: total }, (_, q) => {
    const spec = resolvedByIndex.get(q);
    const rows: React.ReactNode[] = [];
    if (spec !== undefined) {
      rows.push(...keptRowsFor(spec, q));
    }
    const drops = droppedByIndex.get(q);
    if (drops !== undefined) {
      rows.push(...droppedRowsFor(drops, q));
    }
    return (
      <div key={`q-${q}`} className={styles['fblock']}>
        <div className={styles['fhead']}>
          <span className={styles['qord']}>{ordinal(q + 1)} query</span>
        </div>
        {rows.length > 0 ? (
          rows
        ) : (
          <div className={styles['nofilters']}>No filters proposed</div>
        )}
      </div>
    );
  });

  // Orphan drops (no spec_index) — never hide them; show in a trailing block.
  if (orphanDrops.length > 0) {
    blocks.push(
      <div key="q-orphan" className={styles['fblock']}>
        <div className={styles['fhead']}>
          <span className={styles['qord']}>Dropped</span>
        </div>
        {droppedRowsFor(orphanDrops, -1)}
      </div>,
    );
  }

  return <>{blocks}</>;
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
        // The popover reveals the full chunk text; fall back to the snippet for
        // an older payload that did not carry the untruncated `text`.
        const fullText = fieldStr(chunk, 'text') ?? snippet;
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
                  data-full={fullText}
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
    case 'replan':
      return replanBodyNode(d);
    case 'refine':
      return refineBodyNode(d);
    default:
      // synthesise / cache carry their whole detail in the summary line (via
      // phaseDetailNode), so they have no separate body — a duplicate body would
      // render the same lines twice.
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
      return replanBodyNode(d);
    case 'refine':
      return refineBodyNode(d);
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
