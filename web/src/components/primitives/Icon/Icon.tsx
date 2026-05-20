import { cn } from '../../../lib/cn';
import styles from './Icon.module.css';

/**
 * Supported icon names — a closed string-literal union so callers get
 * compile-time checking on every icon reference.
 */
export type IconName =
  | 'search'
  | 'close'
  | 'document'
  | 'external-link'
  | 'chevron-down'
  | 'chevron-right'
  | 'filter'
  | 'info'
  | 'check'
  | 'warning'
  | 'arrow-left'
  | 'tag';

/** Size scale — icons inherit currentColor and scale via token-based dimensions. */
export type IconSize = 'small' | 'medium' | 'large' | 'xlarge';

export interface IconProps {
  /** Which icon to render. */
  name: IconName;
  /**
   * Size of the icon.
   * small = 16 px, medium = 20 px (default), large = 24 px, xlarge = 32 px.
   */
  size?: IconSize;
  /**
   * Accessible label for non-decorative icons.
   * When provided, the SVG gets role="img" and aria-label.
   * When omitted, the SVG is aria-hidden (decorative).
   */
  label?: string;
  /** Additional class names to merge. */
  className?: string;
}

// ─── Inline SVG path data ────────────────────────────────────────────────────
// Each icon is a 24×24 viewBox with paths that respect currentColor via fill or
// stroke. Keeping them inline avoids a network round-trip for an SVG sprite and
// means this component is fully self-contained.

const ICON_PATHS: Record<IconName, React.ReactElement> = {
  search: (
    <path
      d="M21 21l-4.35-4.35M17 11A6 6 0 1 1 5 11a6 6 0 0 1 12 0z"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      fill="none"
    />
  ),
  close: (
    <path
      d="M18 6L6 18M6 6l12 12"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      fill="none"
    />
  ),
  document: (
    <path
      d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6zm0 0v6h6M9 13h6M9 17h6M9 9h1"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      fill="none"
    />
  ),
  'external-link': (
    <path
      d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14L21 3"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      fill="none"
    />
  ),
  'chevron-down': (
    <path
      d="M6 9l6 6 6-6"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      fill="none"
    />
  ),
  'chevron-right': (
    <path
      d="M9 18l6-6-6-6"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      fill="none"
    />
  ),
  filter: (
    <path
      d="M22 3H2l8 9.46V19l4 2v-8.54L22 3z"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      fill="none"
    />
  ),
  info: (
    <>
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="2" fill="none" />
      <path
        d="M12 16v-4M12 8h.01"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        fill="none"
      />
    </>
  ),
  check: (
    <path
      d="M20 6L9 17l-5-5"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      fill="none"
    />
  ),
  warning: (
    <>
      <path
        d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
      <path
        d="M12 9v4M12 17h.01"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        fill="none"
      />
    </>
  ),
  'arrow-left': (
    <path
      d="M19 12H5M12 19l-7-7 7-7"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      fill="none"
    />
  ),
  tag: (
    <path
      d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82zM7 7h.01"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      fill="none"
    />
  ),
};

/**
 * Renders an SVG icon from a closed set of named icons.
 *
 * Decorative use (default): aria-hidden="true", no role.
 * Meaningful use: supply a `label` — the SVG gets role="img" and aria-label.
 *
 * Icons use currentColor so they inherit the surrounding text colour and
 * work correctly on both light and dark backgrounds without token references.
 * Sizing is controlled via CSS tokens in the module.
 */
export function Icon({
  name,
  size = 'medium',
  label,
  className,
}: IconProps): React.ReactElement {
  const classes = cn(
    styles['icon'],
    styles[size],
    className,
  );

  const accessibilityProps = label
    ? { role: 'img' as const, 'aria-label': label }
    : { 'aria-hidden': 'true' as const };

  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      className={classes}
      focusable="false"
      {...accessibilityProps}
    >
      {ICON_PATHS[name]}
    </svg>
  );
}
