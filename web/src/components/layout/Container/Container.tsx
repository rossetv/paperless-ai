import { cn } from '../../../lib/cn';
import styles from './Container.module.css';

export interface ContainerProps {
  children: React.ReactNode;
  className?: string;
}

/**
 * Horizontally centred container capped at --width-app-content, with side padding
 * so content never touches the viewport edge. Composes as Page → Container → Section.
 */
export function Container({ children, className }: ContainerProps): React.ReactElement {
  const classes = cn(styles['container'], className);

  return <div className={classes}>{children}</div>;
}
