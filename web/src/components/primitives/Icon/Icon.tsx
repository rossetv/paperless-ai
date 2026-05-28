import { cn } from '../../../lib/cn';
import styles from './Icon.module.css';

/**
 * Supported icon names — a closed string-literal union so callers get
 * compile-time checking on every icon reference.
 *
 * Internally each name maps to a Font Awesome 7 Free Solid glyph class via
 * `FA_CLASS` below. Add or remove icons in lockstep with that map.
 */
export type IconName =
  | 'search'
  | 'close'
  | 'document'
  | 'external-link'
  | 'chevron-down'
  | 'chevron-right'
  | 'info'
  | 'check'
  | 'warning'
  | 'tag'
  | 'link'
  | 'sparkle'
  | 'waves'
  | 'eye'
  | 'eye-off'
  | 'paragraph'
  | 'lightning'
  | 'list-lines'
  | 'users'
  | 'key'
  | 'library'
  | 'index'
  | 'settings';

/** Size scale — icons inherit currentColor and scale via token-based font-size. */
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
   * When provided, the element gets role="img" and aria-label.
   * When omitted, it is aria-hidden (decorative).
   */
  label?: string;
  /** Additional class names to merge. */
  className?: string;
}

/**
 * Name → Font Awesome 7 Free Solid class.
 *
 * All icons are in the Free Solid set so a single `fa-solid` style class is
 * appended at render time. Keep this map in lockstep with the `IconName`
 * union — TypeScript will flag any drift.
 */
const FA_CLASS: Record<IconName, string> = {
  search: 'fa-magnifying-glass',
  close: 'fa-xmark',
  document: 'fa-file-lines',
  'external-link': 'fa-up-right-from-square',
  'chevron-down': 'fa-chevron-down',
  'chevron-right': 'fa-chevron-right',
  info: 'fa-circle-info',
  check: 'fa-check',
  warning: 'fa-triangle-exclamation',
  tag: 'fa-tag',
  link: 'fa-link',
  sparkle: 'fa-wand-magic-sparkles',
  waves: 'fa-water',
  eye: 'fa-eye',
  'eye-off': 'fa-eye-slash',
  paragraph: 'fa-paragraph',
  lightning: 'fa-bolt',
  'list-lines': 'fa-list',
  users: 'fa-users',
  key: 'fa-key',
  library: 'fa-book',
  index: 'fa-database',
  settings: 'fa-gear',
};

/**
 * Renders a Font Awesome 7 Free Solid icon from a closed set of named icons.
 *
 * Decorative use (default): aria-hidden="true", no role.
 * Meaningful use: supply a `label` — the element gets role="img" and aria-label.
 *
 * Icons use currentColor so they inherit the surrounding text colour and
 * work correctly on both light and dark backgrounds without token references.
 * Sizing is controlled via CSS tokens in the module (font-size based — FA
 * glyphs are a webfont, so font-size is the size knob).
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
    'fa-solid',
    FA_CLASS[name],
    className,
  );

  const accessibilityProps = label
    ? { role: 'img' as const, 'aria-label': label }
    : { 'aria-hidden': 'true' as const };

  return <i className={classes} {...accessibilityProps} />;
}
