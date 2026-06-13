/**
 * ConnectionCard — an accordion card for a single external integration.
 *
 * Shows a brand-neutral glyph tile (service initial), title + subtitle, a
 * connection-status pill (dot + label, toned by ok/err/off/untested), a "Test"
 * button, and a chevron that rotates when expanded. The body is hidden when
 * collapsed.
 *
 * The header toggle is a real `<button>` wrapping only non-interactive content
 * (glyph/title/status/chevron); the "Test" `<button>` is a sibling beside it in
 * a flex row, never nested inside the toggle — so there is no prohibited
 * button-in-button and AT announces two distinct controls.
 *
 * Tier: features/ — composes Icon primitive, uses status tokens.
 */

import React from 'react';
import { Icon } from '../../../components/primitives/Icon/Icon';
import { cn } from '../../../lib/cn';
import styles from './ConnectionCard.module.css';

export type GlyphTone = 'blue' | 'teal' | 'grey';
export type StatusTone = 'ok' | 'err' | 'off' | 'untested';

export interface ConnectionCardProps {
  /** The short text glyph rendered inside the brand-neutral tile. */
  glyph: string;
  /**
   * Retained for API compatibility. The glyph tile is always a brand-neutral
   * fill (`--colour-glyph-neutral`) so it can never be confused with the green
   * "Connected" status dot beside it (DD-1d) — this tone no longer drives the
   * fill colour.
   */
  glyphTone?: GlyphTone;
  /** The card's primary title (integration name). */
  title: string;
  /** Optional one-line subtitle beneath the title. */
  subtitle?: string;
  /** The current connection status to display in the pill. */
  status: { tone: StatusTone; label: string };
  /** Called when the user clicks the "Test" button. Does NOT toggle the card. */
  onTest: () => void;
  /** Whether the card body starts expanded. Defaults to false (collapsed). */
  defaultOpen?: boolean;
  /** The card body — the integration's settings fields. */
  children: React.ReactNode;
}

/**
 * ConnectionCard — accordion integration card with a status pill and test button.
 *
 * The header toggle is a real `<button>` (native click + Enter/Space). The Test
 * `<button>` sits beside it as a sibling, so neither is nested inside the other.
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
      {/* Header row — the toggle button and the Test button as siblings. */}
      <div className={styles['header']}>
        {/* Toggle — a real <button> wrapping only non-interactive content. */}
        <button
          type="button"
          aria-expanded={open}
          aria-label={title}
          className={styles['toggle']}
          onClick={toggle}
        >
          {/* Brand glyph — brand-neutral rounded square (DD-1d) */}
          <span className={styles['glyph']}>{glyph}</span>

          {/* Title + subtitle */}
          <span className={styles['header-info']}>
            <span className={styles['title']}>{title}</span>
            {subtitle !== undefined && (
              <span className={styles['subtitle']}>{subtitle}</span>
            )}
          </span>

          {/* Status pill — role="status" announces changes to assistive tech. */}
          <span
            role="status"
            className={cn(styles['pill'], styles[`pill-${status.tone}`])}
          >
            <span className={styles['pill-dot']} />
            <span className={styles['pill-label']}>{status.label}</span>
          </span>

          {/* Chevron — rotates 180° when expanded */}
          <span
            className={cn(styles['chevron'], open && styles['chevron-open'])}
            aria-hidden="true"
          >
            <Icon name="chevron-down" size="small" />
          </span>
        </button>

        {/* Test button — a sibling of the toggle, never nested inside it. */}
        <button
          type="button"
          className={styles['btn-test']}
          onClick={onTest}
          aria-label={`Test ${title}`}
        >
          Test
        </button>
      </div>

      {/* Body — hidden when collapsed */}
      <div className={styles['body']} hidden={!open}>
        {children}
      </div>
    </div>
  );
}
