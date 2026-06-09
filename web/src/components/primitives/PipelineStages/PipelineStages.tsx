import React from 'react';
import { cn } from '../../../lib/cn';
import { Icon } from '../Icon/Icon';
import styles from './PipelineStages.module.css';

/** Lifecycle state of one pipeline stage. */
export type PipelineStageState = 'done' | 'active' | 'pending';

/**
 * A single document's keep/drop verdict from the relevance judge, rendered as
 * a sublist under the judge stage. `title` falls back to the doc id when null;
 * `reason` is model-generated text shown as escaped text (never HTML).
 */
export interface StageVerdict {
  docId: number;
  title: string | null;
  keep: boolean;
  reason: string;
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

export interface PipelineStagesProps {
  /** The pipeline stages, in execution order. */
  stages: PipelineStage[];
  /** Additional class names to merge. */
  className?: string;
}

/**
 * The agentic-search progress rail.
 *
 * An ordered list of pipeline stages: each row shows a status dot (a tick
 * when done, a pulsing core when active, a muted disc when pending), the
 * stage label and detail, an optional "tokens · cost" chip, an "in progress"
 * pill on the active stage, and — for the judge stage — a kept/dropped
 * per-document verdict sublist. The pulse respects `prefers-reduced-motion`.
 *
 * App-agnostic — it renders whatever stages it is given. `LoadingScreen` maps
 * the live streamed phases onto it; `SearchTracePanel` renders the final trace.
 *
 * Tier: components/primitives (CODE_GUIDELINES §12.3). Allowed deps:
 * primitives (Icon), lib/.
 */
export function PipelineStages({
  stages,
  className,
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
                      {verdict.title ?? `Document ${verdict.docId}`}
                    </span>
                    {verdict.reason !== '' && (
                      <span className={styles['verdict-reason']}>
                        {verdict.reason}
                      </span>
                    )}
                  </span>
                  <span className={styles['verdict-tag']}>
                    {verdict.keep ? 'kept' : 'dropped'}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </li>
      ))}
    </ol>
  );
}
