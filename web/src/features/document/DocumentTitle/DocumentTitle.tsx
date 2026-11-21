import React from 'react';
import styles from './DocumentTitle.module.css';

export interface DocumentTitleProps {
  /** Renders a fallback when null. */
  title: string | null;
  canEdit: boolean;
  /** Called with the trimmed title; not on Escape or when unchanged. */
  onChange: (next: string) => void;
}

/** Smallest font scale before a still-too-long title is left to ellipsise. */
const MIN_TITLE_SCALE = 0.5;

/**
 * Document title heading with optional inline editing. When editable, the
 * `<h1>` acts as a button that swaps to an `<input>`; blur or Enter commits,
 * Escape reverts.
 */
export function DocumentTitle({
  title,
  canEdit,
  onChange,
}: DocumentTitleProps): React.ReactElement {
  const [editing, setEditing] = React.useState(false);
  const [draft, setDraft] = React.useState(title ?? '');

  // Shrink the font just enough to keep a long title on one line. Text width is
  // proportional to font-size, so scaling by clientWidth/scrollWidth fits in a
  // single pass; a title beyond the floor ellipsises.
  const headingRef = React.useRef<HTMLHeadingElement>(null);
  const [scale, setScale] = React.useState(1);

  React.useLayoutEffect(() => {
    const el = headingRef.current;
    if (el === null) return undefined;
    const fit = (): void => {
      el.style.setProperty('--title-scale', '1');
      const { scrollWidth, clientWidth } = el;
      if (clientWidth === 0 || scrollWidth <= clientWidth) {
        setScale(1);
        return;
      }
      setScale(Math.max(MIN_TITLE_SCALE, clientWidth / scrollWidth));
    };
    fit();
    // Re-fit on width changes. ResizeObserver is absent in jsdom / SSR; the
    // one-shot fit above still runs there.
    if (typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(fit);
    observer.observe(el);
    return () => observer.disconnect();
  }, [title, editing]);

  // Sync the draft when the document refreshes, but never clobber an edit in
  // progress.
  React.useEffect(() => {
    if (!editing) setDraft(title ?? '');
  }, [title, editing]);

  function commit(): void {
    setEditing(false);
    const next = draft.trim();
    if (next !== (title ?? '')) onChange(next);
  }

  if (editing) {
    return (
      <input
        className={styles['title-input']}
        value={draft}
        autoFocus
        aria-label="Document title"
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') { e.preventDefault(); commit(); }
          if (e.key === 'Escape') { setDraft(title ?? ''); setEditing(false); }
        }}
      />
    );
  }

  return (
    <h1
      ref={headingRef}
      className={styles['title']}
      style={{ '--title-scale': scale } as React.CSSProperties}
      role={canEdit ? 'button' : undefined}
      tabIndex={canEdit ? 0 : undefined}
      aria-label={canEdit ? `Edit title: ${title ?? 'Untitled document'}` : undefined}
      onClick={canEdit ? () => setEditing(true) : undefined}
      onKeyDown={
        canEdit
          ? (e) => {
              // Match a native button: Enter and Space activate, and Space
              // must not scroll the page.
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                setEditing(true);
              }
            }
          : undefined
      }
    >
      {title ?? 'Untitled document'}
    </h1>
  );
}
