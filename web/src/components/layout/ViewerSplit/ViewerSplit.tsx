import React from 'react';
import { cn } from '../../../lib/cn';
import styles from './ViewerSplit.module.css';

export interface ViewerSplitProps {
  /** The fixed-width metadata sidebar content. */
  sidebar: React.ReactNode;
  /** The flexible main content: the PDF page area. */
  children: React.ReactNode;
  className?: string;
}

/**
 * Document preview body: a flexible page area beside a fixed-width metadata
 * sidebar. Fills the height below the viewer chrome bar and stacks on narrow
 * viewports.
 */
export function ViewerSplit({
  sidebar,
  children,
  className,
}: ViewerSplitProps): React.ReactElement {
  return (
    <div className={cn(styles['split'], className)}>
      <div className={styles['main']}>{children}</div>
      <aside className={styles['sidebar']}>{sidebar}</aside>
    </div>
  );
}
