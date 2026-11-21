import { cn } from '../../../lib/cn';
import styles from './StatusBadge.module.css';

export type StatusTone = 'ok' | 'warn' | 'danger' | 'info' | 'neutral';

export interface StatusBadgeProps {
  /**
   * Semantic tone — `ok` green, `warn` amber, `danger` red, `info` blue,
   * `neutral` grey. Use `neutral` for calm resting states (idle, paused)
   * that are not a caution, reserving `warn` for genuine caution.
   */
  tone: StatusTone;
  /** The label — typically a single short word ("Active", "Suspended"). */
  children: React.ReactNode;
  className?: string;
}

/** Status pill with a leading dot in the tone's colour, e.g. account status or API-key state. */
export function StatusBadge({
  tone,
  children,
  className,
}: StatusBadgeProps): React.ReactElement {
  return (
    <span className={cn(styles['badge'], styles[tone], className)}>
      <span className={styles['dot']} data-testid="status-dot" aria-hidden="true" />
      {children}
    </span>
  );
}
