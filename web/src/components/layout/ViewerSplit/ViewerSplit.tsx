import React from 'react';
import { cn } from '../../../lib/cn';
import styles from './ViewerSplit.module.css';

export interface ViewerSplitProps {
  /** The fixed-width metadata sidebar content. */
  sidebar: React.ReactNode;
  /** The flexible main content — the PDF page area. */
  children: React.ReactNode;
  /** Additional class names to merge. */
  className?: string;
}

/**
 * The document-preview body split.
 *
 * A two-column grid — a flexible page area (`children`) and a fixed-width
 * metadata sidebar — that fills the height below the viewer chrome bar and
 * stacks on narrow viewports.
 *
 * App-agnostic. The `DocumentPreviewScreen` feature supplies both regions.
 *
 * Tier: components/layout (CODE_GUIDELINES §12.3). Allowed deps: lib/.
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
