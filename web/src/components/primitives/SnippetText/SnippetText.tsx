import React from 'react';
import { cn } from '../../../lib/cn';
import styles from './SnippetText.module.css';

export interface SnippetTextProps {
  /**
   * The snippet text. `**phrase**` runs are rendered as accent highlights.
   * An empty string renders a short accessible "no excerpt" notice instead.
   */
  text: string;
  /** Additional class names to merge onto the paragraph. */
  className?: string;
}

/**
 * Split a snippet on `**bold**` runs.
 *
 * The capturing split yields alternating plain / bold segments: even indices
 * are plain text, odd indices are the emphasised phrase. This is the same
 * `**…**` convention the search backend emits in `snippet` fields.
 */
function splitBoldRuns(text: string): string[] {
  return text.split(/\*\*([^*]+)\*\*/g);
}

/**
 * A matched-content snippet with `**bold**` runs highlighted.
 *
 * Renders the excerpt as body text; each `**phrase**` becomes an accent
 * `<mark>`. An empty snippet renders a tertiary "No excerpt available."
 * notice so the component never leaves an unexplained blank gap.
 *
 * Tier: components/primitives (CODE_GUIDELINES §12.3). Allowed deps: lib/.
 */
export function SnippetText({
  text,
  className,
}: SnippetTextProps): React.ReactElement {
  if (text.length === 0) {
    return (
      <p className={cn(styles['snippet'], styles['empty'], className)}>
        No excerpt available.
      </p>
    );
  }

  const segments = splitBoldRuns(text);

  return (
    <p className={cn(styles['snippet'], className)}>
      {segments.map((segment, i) =>
        i % 2 === 0 ? (
          <React.Fragment key={i}>{segment}</React.Fragment>
        ) : (
          <mark key={i} className={styles['mark']}>
            {segment}
          </mark>
        ),
      )}
    </p>
  );
}
