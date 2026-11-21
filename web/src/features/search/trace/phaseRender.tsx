/**
 * Renders search-trace phases as `PipelineStages` rows. The live rail and the
 * folded trace panel both use this mapping, so the two never drift.
 */

import React from 'react';
import type { PhaseRecord, SearchPhase } from '../../../api/types';
import type {
  PipelineStage,
  PipelineStageState,
} from '../../../components/primitives/PipelineStages/PipelineStages';
import { formatCostLabel, ordinal } from './costFormat';
import {
  bool,
  fieldNum,
  fieldNumList,
  fieldObj,
  fieldStr,
  fieldStrList,
  num,
  objList,
  str,
  verdictsOf,
} from './detailAccessors';
import styles from './phaseStages.module.css';

/** Labels for an active phase, before its record (with the server's label) arrives. */
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

/** Stacks short text lines; null for an empty list so the caller can fall back. */
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

function filterChip(key: string, label: string, value: string): React.ReactNode {
  return (
    <span key={key} className={styles['qfilter']}>
      <span className={styles['qfilter-key']}>{label} </span>
      {value}
    </span>
  );
}

/**
 * Filter chips for one query block. Plan and replan carry free-text guesses,
 * refine carries resolved ids; the shapes are disjoint, so one renderer serves all.
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

/** Search specs as query blocks, shared by the plan, replan and refine phases. */
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

/** A context line ("Gap", "Action") above a replan or refine query list. */
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

/** Plain-text resolve detail: resolved ids per spec, then the dropped guesses. */
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

/** New searches, or a note that the replan asked to clarify (refinement ignores it). */
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

/** 1 → "1 chunk", 2 → "2 chunks"; handles "search" → "searches". */
function plural(count: number, noun: string): string {
  if (count === 1) {
    return `${count} ${noun}`;
  }
  const suffix = noun.endsWith('ch') ? 'es' : 's';
  return `${count} ${noun}${suffix}`;
}

/**
 * Accepts both the object shape ({correspondent: {id, name, method}}) and the
 * legacy id shape ({correspondent_id: 7}).
 */
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

/** "<head> · K keyword, S semantic", with `head` accent-styled. */
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
 * A phase's one-line summary: the always-visible row text in the trace and the
 * only text on the live rail.
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
        // Legacy shape or clarify: no specs, only a rewritten query.
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

// Matches the planning step's chip labels.
const RESOLVE_DIM_LABEL: Record<string, string> = {
  correspondent: 'from',
  document_type: 'type',
  tags: 'tags',
};

// For the "no matching …" drop reason.
const RESOLVE_DIM_NOUN: Record<string, string> = {
  correspondent: 'correspondent',
  document_type: 'document type',
  tags: 'tag',
};

/**
 * A kept filter row with an optional annotation (e.g. `loosened from "Deed"`).
 * The ✓ is decorative; the chip styling carries the outcome too.
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

/** A dropped filter row: struck-through chip plus the reason it was dropped. */
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
 * The resolve body: one block per planned query listing every filter as kept,
 * loosened or dropped. Drops are grouped by `spec_index`; legacy drops without
 * one go in a trailing block so none is hidden. Legacy id-only specs render as
 * `#id`.
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

  function guessFor(index: number, key: string): string | null {
    const planSpec = planSpecs[index];
    if (planSpec === undefined) {
      return null;
    }
    const filters = (planSpec['filters'] ?? {}) as Record<string, unknown>;
    return fieldStr(filters, key);
  }

  const resolvedByIndex = new Map<number, Record<string, unknown>>();
  resolved.forEach((spec, i) => {
    resolvedByIndex.set(fieldNum(spec, 'spec_index') ?? i, spec);
  });

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
      const legacyId = fieldNum(spec, `${key}_id`);
      if (legacyId !== null) {
        rows.push(keptFilterRow(`${key}-${index}`, dim, `#${legacyId}`));
      }
    }

    renderField('correspondent', 'from', 'correspondent');
    renderField('document_type', 'type', 'document_type');

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
      // Legacy shape {spec_index, names}: no field or reason.
      fieldStrList(entry, 'names').forEach((nm, ni) => {
        rows.push(
          droppedFilterRow(`dropn-${index}-${di}-${ni}`, null, nm, 'no match'),
        );
      });
    });
    return rows;
  }

  // Fall back to the highest index seen when plan specs were not passed in.
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
 * One row per retrieved chunk. The snippet carries the full text in data
 * attributes for the shared ChunkPopover.
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
        // Older payloads carry no untruncated `text`.
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

/** One row per evaluated document, with a bar for its best vector similarity. */
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
                <i style={{ width: `${pct}%` }} />
              </div>
            </span>
          </div>
        );
      })}
    </div>
  );
}

/**
 * A phase's expandable body, or null when the summary says it all. `planSpecs`
 * lets the resolve body name what a loosened match was loosened from.
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
      // PipelineStages renders the verdict list from `verdicts`.
      return null;
    case 'replan':
      return replanBodyNode(d);
    case 'refine':
      return refineBodyNode(d);
    default:
      // synthesise and cache show everything in the summary line; a body would
      // repeat it.
      return null;
  }
}

/** The detail node rendered under a phase's label, or null when there is nothing to show. */
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

/**
 * Maps completed phases to `done` rows, plus a trailing `active` row for
 * `activePhase`. Pass null for a finished trace.
 */
export function phaseToStages(
  records: PhaseRecord[],
  activePhase: SearchPhase | null,
): PipelineStage[] {
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

  // No duplicate row can persist: the reducer clears activePhase on phase_done.
  if (activePhase !== null) {
    stages.push({
      label: PHASE_LABELS[activePhase],
      detail: '',
      state: 'active',
    });
  }

  return stages;
}
