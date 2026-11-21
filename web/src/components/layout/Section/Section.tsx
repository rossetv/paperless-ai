import { cn } from '../../../lib/cn';
import styles from './Section.module.css';

export interface SectionProps {
  /**
   * Generous vertical padding for top-level page sections. The default is
   * compact, for sub-sections within a page.
   */
  spacious?: boolean;
  children: React.ReactNode;
  className?: string;
}

/** Semantic `<section>` with vertical padding from the spacing scale. */
export function Section({ spacious = false, children, className }: SectionProps): React.ReactElement {
  const classes = cn(
    styles['section'],
    spacious ? styles['spacious'] : undefined,
    className,
  );

  return <section className={classes}>{children}</section>;
}
