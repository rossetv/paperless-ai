import React from 'react';
import { cn } from '../../../lib/cn';
import { Icon } from '../Icon/Icon';
import styles from './PipelineStages.module.css';

/** Lifecycle state of one pipeline stage. */
export type PipelineStageState = 'done' | 'active' | 'pending';

/** One stage of the agentic-search pipeline. */
export interface PipelineStage {
  /** Short stage name, e.g. "Planning the query". */
  label: string;
  /** A one-line description of what the stage does. */
  detail: string;
  /** Lifecycle state — drives the dot styling and the "in progress" pill. */
  state: PipelineStageState;
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
 * stage label and detail, and an "in progress" pill on the active stage.
 * The pulse respects `prefers-reduced-motion`.
 *
 * App-agnostic — it renders whatever stages it is given. `LoadingScreen`
 * supplies the three search-pipeline stages.
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
          <span className={styles['dot']} aria-hidden="true">
            {stage.state === 'done' && <Icon name="check" size="small" />}
            {stage.state === 'active' && (
              <span className={styles['pulse']} />
            )}
          </span>

          <span className={styles['text']}>
            <span className={styles['label']}>{stage.label}</span>
            <span className={styles['detail']}>{stage.detail}</span>
          </span>

          {stage.state === 'active' && (
            <span className={styles['progress-pill']}>in progress</span>
          )}
        </li>
      ))}
    </ol>
  );
}
