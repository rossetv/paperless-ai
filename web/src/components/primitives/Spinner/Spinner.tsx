import { cn } from '../../../lib/cn';
import styles from './Spinner.module.css';

export type SpinnerSize = 'small' | 'medium' | 'large';

export interface SpinnerProps {
  /** Accessible label. Defaults to "Loading…". */
  label?: string;
  /** Size of the spinner ring. Defaults to 'medium'. */
  size?: SpinnerSize;
  className?: string;
}

/**
 * Loading indicator with role="status", so screen readers announce the visually
 * hidden label without interrupting.
 */
export function Spinner({
  label = 'Loading…',
  size = 'medium',
  className,
}: SpinnerProps): React.ReactElement {
  const classes = cn(styles['spinner'], styles[size], className);

  return (
    <span role="status" aria-label={label} className={classes}>
      <span className={styles['ring']} aria-hidden="true" />
      <span className="visually-hidden">{label}</span>
    </span>
  );
}
