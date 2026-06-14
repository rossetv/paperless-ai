import React from 'react';
import styles from './DocumentTitle.module.css';

export interface DocumentTitleProps {
  /** The document title; renders a fallback when null. */
  title: string | null;
  /** Whether the current user may edit the title. */
  canEdit: boolean;
  /**
   * Called with the trimmed new title when the user commits an edit.
   * Not called on revert, Escape, or when the value is unchanged.
   */
  onChange: (next: string) => void;
}

/**
 * Document title heading with optional inline editing.
 *
 * Read-only (`canEdit=false`): renders a plain `<h1>` — correct heading
 * semantics for assistive tech.
 *
 * Editable (`canEdit=true`): the `<h1>` carries `role="button"` and responds
 * to click / Enter by switching to an `<input>`. Blur or Enter commits the
 * value (only fires `onChange` when it actually changed); Escape reverts.
 */
/** Smallest font scale before a still-too-long title is left to ellipsise. */
const MIN_TITLE_SCALE = 0.5;

export function DocumentTitle({
  title,
  canEdit,
  onChange,
}: DocumentTitleProps): React.ReactElement {
  const [editing, setEditing] = React.useState(false);
  const [draft, setDraft] = React.useState(title ?? '');

  // Adaptive heading size: shrink the font just enough to keep a long title on
  // one line (the design preferred over wrapping). Text width is proportional
  // to font-size, so scaling by clientWidth/scrollWidth fits in a single pass;
  // a title beyond the floor ellipsises rather than becoming unreadable.
  const headingRef = React.useRef<HTMLHeadingElement>(null);
  const [scale, setScale] = React.useState(1);

  React.useLayoutEffect(() => {
    const el = headingRef.current;
    if (el === null) return undefined;
    const fit = (): void => {
      // Measure at full size, then derive the scale that fits the row width.
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

  // Keep draft in sync when the parent document is refreshed (e.g. post-save),
  // but never clobber an in-progress edit: a cache refresh while the user is
  // typing must not overwrite their unsaved draft (FE-24).
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
              // Enter and Space both enter edit mode; preventDefault on both so
              // Space doesn't scroll the page and the activation matches a
              // native button's keyboard contract (FE-25).
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
