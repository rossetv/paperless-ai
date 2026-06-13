import { cn } from '../../../lib/cn';
import styles from './StatusBadge.module.css';

/** The semantic tone of a StatusBadge — drives its colour. */
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
  /** Additional class names to merge. */
  className?: string;
}

/**
 * Small status pill with a leading colour dot.
 *
 * Renders a non-interactive `<span>`: a coloured dot followed by the label.
 * The dot takes the tone's foreground colour via `currentColor`. Used for
 * account status and API-key state.
 *
 * Tier: components/primitives (CODE_GUIDELINES §12.3). Allowed deps: lib/.
 */
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
