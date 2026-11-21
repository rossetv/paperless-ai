import React from 'react';
import { cn } from '../../../lib/cn';
import styles from './SnippetText.module.css';

export interface SnippetTextProps {
  /**
   * The snippet text. `**phrase**` runs are rendered as accent highlights.
   * An empty string renders a short accessible "no excerpt" notice instead.
   */
  text: string;
  className?: string;
}

/**
 * Split on `**bold**` runs, the convention the search backend uses in `snippet`
 * fields: even indices are plain text, odd indices the emphasised phrase.
 */
function splitBoldRuns(text: string): string[] {
  return text.split(/\*\*([^*]+)\*\*/g);
}

/**
 * Matched-content snippet with `**bold**` runs rendered as accent `<mark>`s. An
 * empty snippet shows a "No excerpt available." notice instead of a blank gap.
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
