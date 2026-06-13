import React, { useRef } from 'react';
import { cn } from '../../../lib/cn';
import { Icon } from '../Icon/Icon';
import { Button } from '../Button/Button';
import { ChunkPopover } from './ChunkPopover';
import styles from './PipelineStages.module.css';

/** Lifecycle state of one pipeline stage. */
export type PipelineStageState = 'done' | 'active' | 'pending';

/**
 * A single document's keep/drop verdict from the relevance judge, rendered as
 * a sublist under the judge stage. `title` falls back to the doc id when null;
 * `reason` is model-generated text shown as escaped text (never HTML).
 *
 * `score` is the judge's 0–1 relevance score (null when the wire omitted it);
 * `paperlessUrl` is the document's deep link, present so the row can offer a
 * preview control. Both come from the judge phase's per-document detail.
 */
export interface StageVerdict {
  docId: number;
  title: string | null;
  keep: boolean;
  reason: string;
  score: number | null;
  paperlessUrl: string | null;
}

/** One stage of the agentic-search pipeline. */
export interface PipelineStage {
  /** Short stage name, e.g. "Planning the query". */
  label: string;
  /**
   * A one-line description of what the stage does. Used when no richer
   * `detailNode` is supplied — kept for back-compat with the static rail.
   */
  detail: string;
  /** Lifecycle state — drives the dot styling and the "in progress" pill. */
  state: PipelineStageState;
  /**
   * A rich detail node rendered in place of `detail` when present (e.g. the
   * planner's rewritten query as an emphasised run). Falls back to `detail`.
   */
  detailNode?: React.ReactNode;
  /**
   * A one-line phase summary shown on the stage row (e.g. "3 searches planned").
   * In collapsible mode this is the always-visible `<summary>` line; in the
   * lean live rail it is the only thing shown. Falls back to `detailNode`/`detail`.
   */
  summary?: React.ReactNode;
  /**
   * The expandable rich detail for the phase, shown only in collapsible mode
   * inside the disclosure body (e.g. the per-spec search list, the resolved
   * filters, the retrieved chunks). Absent for phases with nothing to expand.
   */
  body?: React.ReactNode;
  /**
   * A compact "tokens · cost" label (e.g. "1.2k tok · $0.004"), shown as a chip
   * on the stage row. Absent for non-LLM stages.
   */
  costLabel?: string;
  /**
   * The judge's per-document verdicts, rendered as a kept/dropped sublist under
   * the stage. Only the judge stage supplies these.
   */
  verdicts?: StageVerdict[];
}

/**
 * Format a 0–1 judge relevance score as a two-decimal string (e.g. 0.87 →
 * "0.87"). A score outside the expected range is still rendered as-is — the
 * judge owns the scale; this is a display helper, not a validator.
 */
function formatScore(score: number): string {
  return score.toFixed(2);
}

export interface PipelineStagesProps {
  /** The pipeline stages, in execution order. */
  stages: PipelineStage[];
  /** Additional class names to merge. */
  className?: string;
  /**
   * Whether the rail is the folded final trace (true) or the lean live rail
   * (false / omitted). When collapsible, a stage that has a `body` or verdicts
   * renders as a `<details>` disclosure whose summary line is always shown and
   * whose rich body expands on click. When NOT collapsible, every stage renders
   * a single plain row showing only its summary — no body, no verdicts — so the
   * live rail stays lean while a search is running.
   */
  collapsible?: boolean;
  /**
   * Called with a document id when a judged document's "View" control is
   * activated. When supplied, each verdict row renders a View button that
   * opens the in-app document viewer for that id; when omitted (e.g. a context
   * with no document-open handler) the rows render without the control.
   */
  onPreviewDocument?: (documentId: number) => void;
}

/** The judge's per-document verdict list, shown inside a collapsible stage's
 *  expanded body. Each row carries the score, title, reason, keep/drop tag and
 *  an optional "View" control that opens the in-app document viewer. */
function VerdictList({
  verdicts,
  onPreviewDocument,
}: {
  verdicts: StageVerdict[];
  onPreviewDocument?: (documentId: number) => void;
}): React.ReactElement {
  return (
    <ul className={styles['verdicts']}>
      {verdicts.map((verdict) => (
        <li
          key={verdict.docId}
          className={styles['verdict']}
          data-keep={verdict.keep}
        >
          <span className={styles['verdict-dot']} aria-hidden="true" />
          <span className={styles['verdict-text']}>
            <span className={styles['verdict-title']}>
              {verdict.score !== null && (
                <span className={styles['verdict-score']}>
                  {formatScore(verdict.score)}
                </span>
              )}
              {verdict.title ?? `Document ${verdict.docId}`}
            </span>
            {verdict.reason !== '' && (
              <span className={styles['verdict-reason']}>{verdict.reason}</span>
            )}
          </span>
          <span className={styles['verdict-tag']}>
            {verdict.keep ? 'keep' : 'drop'}
          </span>
          {onPreviewDocument !== undefined && (
            <span className={styles['verdict-action']}>
              <Button
                variant="ghost"
                size="small"
                onClick={() => onPreviewDocument(verdict.docId)}
              >
                View
              </Button>
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}

/** The status dot for a stage row — a tick when done, a pulsing core when
 *  active, an empty disc otherwise. */
function StageDot({ state }: { state: PipelineStageState }): React.ReactElement {
  return (
    <span className={styles['dot']} aria-hidden="true">
      {state === 'done' && <Icon name="check" size="small" />}
      {state === 'active' && <span className={styles['pulse']} />}
    </span>
  );
}

/**
 * The agentic-search progress rail.
 *
 * An ordered list of pipeline stages: each row shows a status dot (a tick
 * when done, a pulsing core when active, a muted disc when pending), the
 * stage label and detail, an optional "tokens · cost" chip, an "in progress"
 * pill on the active stage, and — for the judge stage — a keep/drop
 * per-document verdict sublist (score · title · reason, with an optional
 * View control when `onPreviewDocument` is supplied). The pulse respects
 * `prefers-reduced-motion`.
 *
 * In `collapsible` mode each stage with a rich `body` (or verdicts) becomes a
 * native `<details>` disclosure: the summary line is always visible and the
 * body expands on click. Without `collapsible` (the live rail) only the
 * summary line is shown — no body, no verdicts — keeping the in-flight rail
 * lean.
 *
 * App-agnostic — it renders whatever stages it is given. `LoadingScreen` maps
 * the live streamed phases onto it; `SearchTracePanel` renders the final trace.
 * Both thread the page's document-open handler in as `onPreviewDocument`.
 *
 * Tier: components/primitives (CODE_GUIDELINES §12.3). Allowed deps:
 * primitives (Icon, Button), lib/.
 */
export function PipelineStages({
  stages,
  className,
  collapsible = false,
  onPreviewDocument,
}: PipelineStagesProps): React.ReactElement {
  // The <ol> hosts the shared ChunkPopover: it listens for hover/focus on the
  // retrieve-body `.chunk-snip` elements rendered inside the disclosure bodies.
  const olRef = useRef<HTMLOListElement | null>(null);

  return (
    <>
      <ol ref={olRef} className={cn(styles['stages'], className)}>
        {stages.map((stage, i) => {
          const summaryContent = stage.summary ?? stage.detailNode ?? stage.detail;
          // Narrow once: a non-empty verdict list, or undefined. Carrying the
          // narrowed value lets the body pass it without an `as` cast (FE-57).
          const verdicts =
            stage.verdicts !== undefined && stage.verdicts.length > 0
              ? stage.verdicts
              : undefined;
          const expandable =
            collapsible && (stage.body != null || verdicts !== undefined);

          return (
            <li key={i} className={styles['stage']} data-state={stage.state}>
              {expandable ? (
                <details className={styles['stage-disclosure']}>
                  <summary className={styles['stage-summary-row']}>
                    <div className={styles['row']}>
                      <StageDot state={stage.state} />
                      <span className={styles['text']}>
                        <span className={styles['label']}>{stage.label}</span>
                        <span className={styles['detail']}>{summaryContent}</span>
                      </span>
                      {/* The per-stage cost chip sits on the always-visible
                          summary row, right-aligned, so every stage shows its
                          per-step tokens · cost without being expanded — the
                          collapsed row is the read-out (UI-16). */}
                      {stage.costLabel !== undefined && (
                        <span className={styles['cost-chip']}>{stage.costLabel}</span>
                      )}
                      <svg
                        className={styles['chevron']}
                        viewBox="0 0 16 16"
                        fill="none"
                        aria-hidden="true"
                      >
                        <path
                          d="M6 4l4 4-4 4"
                          stroke="currentColor"
                          strokeWidth="1.6"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        />
                      </svg>
                    </div>
                  </summary>
                  <div className={styles['stage-body']}>
                    {stage.body}
                    {verdicts !== undefined && (
                      <VerdictList
                        verdicts={verdicts}
                        {...(onPreviewDocument !== undefined
                          ? { onPreviewDocument }
                          : {})}
                      />
                    )}
                  </div>
                </details>
              ) : (
                <div className={styles['row']}>
                  <StageDot state={stage.state} />
                  <span className={styles['text']}>
                    <span className={styles['label']}>{stage.label}</span>
                    <span className={styles['detail']}>{summaryContent}</span>
                  </span>
                  {stage.costLabel !== undefined && (
                    <span className={styles['cost-chip']}>{stage.costLabel}</span>
                  )}
                  {stage.state === 'active' && (
                    <span className={styles['progress-pill']}>in progress</span>
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ol>
      <ChunkPopover containerRef={olRef as React.RefObject<HTMLElement | null>} />
    </>
  );
}
