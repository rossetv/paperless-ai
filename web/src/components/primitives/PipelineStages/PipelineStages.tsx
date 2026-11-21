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
  /** One-line description, used when no richer `detailNode` is supplied. */
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
 * Two-decimal display of a judge score. Out-of-range values are shown as-is;
 * the judge owns the scale.
 */
function formatScore(score: number): string {
  return score.toFixed(2);
}

export interface PipelineStagesProps {
  /** The pipeline stages, in execution order. */
  stages: PipelineStage[];
  className?: string;
  /**
   * Folded final trace (true) or lean live rail (false). When collapsible, a
   * stage with a `body` or verdicts renders as a `<details>` disclosure; otherwise
   * every stage is a single row showing only its summary.
   */
  collapsible?: boolean;
  /**
   * Called with a document id from a verdict row's "View" control. When omitted,
   * the rows render without the control.
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
 * Agentic-search progress rail: an ordered list of stages, each with a status
 * dot, label, detail, optional cost chip and, for the judge stage, a keep/drop
 * verdict sublist.
 *
 * `LoadingScreen` maps the live streamed phases onto it; `SearchTracePanel`
 * renders the final trace with `collapsible`.
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
          // Narrow once so the body can take the verdicts without an `as` cast.
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
                      {/* On the always-visible summary row, so the collapsed row
                          shows each stage's tokens · cost. */}
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
                    <span
                      className={cn(
                        styles['cost-chip'],
                        // In the folded trace this row has no chevron; reserve its
                        // slot so the chip aligns with the chevroned rows above.
                        collapsible && styles['cost-chip-aligned'],
                      )}
                    >
                      {stage.costLabel}
                    </span>
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
