/**
 * ConnectionCard — an accordion card for a single external integration.
 *
 * Shows a coloured glyph (brand initial), title + subtitle, a connection-status
 * pill (dot + label, toned by ok/err/off/untested), a "Test" button, and a
 * chevron that rotates when expanded. The body is hidden when collapsed.
 *
 * The header is a `role="button"` element so click and keyboard (Enter/Space)
 * both toggle it. The Test button calls `e.stopPropagation()` so it never
 * triggers the accordion toggle.
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
  /** The short text glyph rendered inside the coloured rounded square. */
  glyph: string;
  /** The background colour tone of the glyph square. */
  glyphTone: GlyphTone;
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
 * Header toggles expand/collapse via click and Enter/Space keyboard events.
 * The Test button stops propagation so it never triggers the accordion toggle.
 */
export function ConnectionCard({
  glyph,
  glyphTone,
  title,
  subtitle,
  status,
  onTest,
  defaultOpen = false,
  children,
}: ConnectionCardProps): React.ReactElement {
  const [open, setOpen] = React.useState(defaultOpen);

  const toggle = (): void => setOpen((prev) => !prev);

  const handleHeaderKeyDown = (e: React.KeyboardEvent<HTMLDivElement>): void => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      toggle();
    }
  };

  const handleTestClick = (e: React.MouseEvent<HTMLButtonElement>): void => {
    e.stopPropagation();
    onTest();
  };

  return (
    <div className={styles['card']}>
      {/* Header — role="button" so click + keyboard toggle the accordion. */}
      <div
        role="button"
        tabIndex={0}
        aria-expanded={open}
        aria-label={title}
        className={styles['header']}
        onClick={toggle}
        onKeyDown={handleHeaderKeyDown}
      >
        {/* Brand glyph — coloured rounded square */}
        <span className={cn(styles['glyph'], styles[`glyph-${glyphTone}`])}>
          {glyph}
        </span>

        {/* Title + subtitle */}
        <div className={styles['header-info']}>
          <span className={styles['title']}>{title}</span>
          {subtitle !== undefined && (
            <span className={styles['subtitle']}>{subtitle}</span>
          )}
        </div>

        {/* Status pill — role="status" announces changes to assistive tech. */}
        <span
          role="status"
          className={cn(styles['pill'], styles[`pill-${status.tone}`])}
        >
          <span className={styles['pill-dot']} />
          <span className={styles['pill-label']}>{status.label}</span>
        </span>

        {/* Test button — stopPropagation so it never toggles the card */}
        <button
          type="button"
          className={styles['btn-test']}
          onClick={handleTestClick}
          aria-label={`Test ${title}`}
        >
          Test
        </button>

        {/* Chevron — rotates 180° when expanded */}
        <span
          className={cn(styles['chevron'], open && styles['chevron-open'])}
          aria-hidden="true"
        >
          <Icon name="chevron-down" size="small" />
        </span>
      </div>

      {/* Body — hidden when collapsed */}
      <div className={styles['body']} hidden={!open}>
        {children}
      </div>
    </div>
  );
}
