import React from 'react';
import { Icon } from '../../../components/primitives/Icon/Icon';
import { cn } from '../../../lib/cn';
import styles from './ConnectionCard.module.css';

export type GlyphTone = 'blue' | 'teal' | 'grey';
export type StatusTone = 'ok' | 'err' | 'off' | 'untested';

export interface ConnectionCardProps {
  glyph: string;
  /**
   * Unused: the glyph tile is always a neutral fill so it can never be confused
   * with the green "Connected" status dot. Kept so existing callers still compile.
   */
  glyphTone?: GlyphTone;
  title: string;
  subtitle?: string;
  status: { tone: StatusTone; label: string };
  /** Called when the user clicks the "Test" button. Does NOT toggle the card. */
  onTest: () => void;
  /** Defaults to false (collapsed). */
  defaultOpen?: boolean;
  children: React.ReactNode;
}

/**
 * Accordion card for one external integration, with a status pill and a Test button.
 *
 * The header toggle is a real `<button>` wrapping only non-interactive content; the Test
 * `<button>` is its sibling, never nested inside it, so there is no button-in-button and
 * assistive tech announces two distinct controls.
 */
export function ConnectionCard({
  glyph,
  title,
  subtitle,
  status,
  onTest,
  defaultOpen = false,
  children,
}: ConnectionCardProps): React.ReactElement {
  const [open, setOpen] = React.useState(defaultOpen);

  const toggle = (): void => setOpen((prev) => !prev);

  return (
    <div className={styles['card']}>
      <div className={styles['header']}>
        <button
          type="button"
          aria-expanded={open}
          className={styles['toggle']}
          onClick={toggle}
        >
          <span className={styles['glyph']} aria-hidden="true">{glyph}</span>

          <span className={styles['header-info']}>
            <span className={styles['title']}>{title}</span>
            {subtitle !== undefined && (
              <span className={styles['subtitle']}>{subtitle}</span>
            )}
          </span>

          <span
            role="status"
            className={cn(styles['pill'], styles[`pill-${status.tone}`])}
          >
            <span className={styles['pill-dot']} />
            <span className={styles['pill-label']}>{status.label}</span>
          </span>

          <span
            className={cn(styles['chevron'], open && styles['chevron-open'])}
            aria-hidden="true"
          >
            <Icon name="chevron-down" size="small" />
          </span>
        </button>

        <button
          type="button"
          className={styles['btn-test']}
          onClick={onTest}
          aria-label={`Test ${title}`}
        >
          Test
        </button>
      </div>

      <div className={styles['body']} hidden={!open}>
        {children}
      </div>
    </div>
  );
}
