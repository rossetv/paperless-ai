import React from 'react';
import { cn } from '../../../lib/cn';
import styles from './ViewToggle.module.css';

/** The two library layout modes. */
export type LibraryView = 'grid' | 'list';

export interface ViewToggleProps {
  value: LibraryView;
  /**
   * Called with the newly selected view. Not called when the user clicks the
   * already-active segment.
   */
  onChange: (view: LibraryView) => void;
  className?: string;
}

interface Segment {
  view: LibraryView;
  label: string;
  /** 12×12 viewBox SVG path content — purely decorative. */
  glyph: React.ReactNode;
}

/*
 * Inline 12×12 glyphs (a 2×2 grid, three stacked rules): too small and one-off
 * for an Icon-set entry.
 */
const SEGMENTS: readonly Segment[] = [
  {
    view: 'grid',
    label: 'Grid',
    glyph: (
      <>
        <rect x="1" y="1" width="4" height="4" rx="1" />
        <rect x="7" y="1" width="4" height="4" rx="1" />
        <rect x="1" y="7" width="4" height="4" rx="1" />
        <rect x="7" y="7" width="4" height="4" rx="1" />
      </>
    ),
  },
  {
    view: 'list',
    label: 'List',
    glyph: (
      <>
        <line x1="1" y1="2.5" x2="11" y2="2.5" />
        <line x1="1" y1="6" x2="11" y2="6" />
        <line x1="1" y1="9.5" x2="11" y2="9.5" />
      </>
    ),
  },
];

/**
 * Controlled grid/list segmented switch: two `aria-pressed` buttons in a
 * `role="group"`. Clicking the active segment does not call `onChange`.
 */
export function ViewToggle({
  value,
  onChange,
  className,
}: ViewToggleProps): React.ReactElement {
  return (
    <div className={cn(styles['toggle'], className)} role="group" aria-label="View">
      {SEGMENTS.map((segment) => {
        const isActive = segment.view === value;
        return (
          <button
            key={segment.view}
            type="button"
            aria-pressed={isActive}
            className={cn(styles['segment'], isActive && styles['active'])}
            onClick={() => {
              if (!isActive) {
                onChange(segment.view);
              }
            }}
          >
            <span className={styles['icon']} aria-hidden="true">
              <svg
                width="12"
                height="12"
                viewBox="0 0 12 12"
                fill="currentColor"
                stroke="currentColor"
                strokeWidth="1.4"
                strokeLinecap="round"
              >
                {segment.glyph}
              </svg>
            </span>
            {segment.label}
          </button>
        );
      })}
    </div>
  );
}
