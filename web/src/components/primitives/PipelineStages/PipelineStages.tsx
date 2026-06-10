import React from 'react';
import { cn } from '../../../lib/cn';
import { Icon } from '../Icon/Icon';
import { Button } from '../Button/Button';
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
   * Called with a document id when a judged document's "Preview" control is
   * activated. When supplied, each verdict row renders a Preview button that
   * opens the in-app document viewer for that id; when omitted (e.g. a context
   * with no document-open handler) the rows render without the control.
   */
  onPreviewDocument?: (documentId: number) => void;
}

/**
 * The agentic-search progress rail.
 *
 * An ordered list of pipeline stages: each row shows a status dot (a tick
 * when done, a pulsing core when active, a muted disc when pending), the
 * stage label and detail, an optional "tokens · cost" chip, an "in progress"
 * pill on the active stage, and — for the judge stage — a keep/drop
 * per-document verdict sublist (score · title · reason, with an optional
 * Preview control when `onPreviewDocument` is supplied). The pulse respects
 * `prefers-reduced-motion`.
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
  onPreviewDocument,
}: PipelineStagesProps): React.ReactElement {
  return (
    <ol className={cn(styles['stages'], className)}>
      {stages.map((stage, i) => (
        <li key={i} className={styles['stage']} data-state={stage.state}>
          <div className={styles['row']}>
            <span className={styles['dot']} aria-hidden="true">
              {stage.state === 'done' && <Icon name="check" size="small" />}
              {stage.state === 'active' && (
                <span className={styles['pulse']} />
              )}
            </span>

            <span className={styles['text']}>
              <span className={styles['label']}>{stage.label}</span>
              <span className={styles['detail']}>
                {stage.detailNode ?? stage.detail}
              </span>
            </span>

            {stage.costLabel !== undefined && (
              <span className={styles['cost-chip']}>{stage.costLabel}</span>
            )}

            {stage.state === 'active' && (
              <span className={styles['progress-pill']}>in progress</span>
            )}
          </div>

          {stage.verdicts !== undefined && stage.verdicts.length > 0 && (
            <ul className={styles['verdicts']}>
              {stage.verdicts.map((verdict) => (
                <li
                  key={verdict.docId}
                  className={styles['verdict']}
                  data-keep={verdict.keep}
                >
                  <span
                    className={styles['verdict-dot']}
                    aria-hidden="true"
                  />
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
                      <span className={styles['verdict-reason']}>
                        {verdict.reason}
                      </span>
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
                        Preview
                      </Button>
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </li>
      ))}
    </ol>
  );
}
