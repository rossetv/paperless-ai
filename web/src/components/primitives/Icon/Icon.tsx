import { cn } from '../../../lib/cn';
import styles from './Icon.module.css';

/** Supported icon names; each maps to a Font Awesome 7 Free Solid class in `FA_CLASS`. */
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
  | 'settings'
  | 'tags'
  | 'gears'
  | 'arrows-rotate'
  | 'arrow-up'
  | 'arrow-down';

export type IconSize = 'small' | 'medium' | 'large' | 'xlarge';

export interface IconProps {
  name: IconName;
  /** small = 16 px, medium = 20 px (default), large = 24 px, xlarge = 32 px. */
  size?: IconSize;
  /** Accessible label. When set the icon gets role="img"; otherwise it is aria-hidden. */
  label?: string;
  className?: string;
}

/** All icons are Free Solid, so one `fa-solid` class is appended at render time. */
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
  tags: 'fa-tags',
  gears: 'fa-gears',
  'arrows-rotate': 'fa-arrows-rotate',
  'arrow-up': 'fa-arrow-up',
  'arrow-down': 'fa-arrow-down',
};

/** Font Awesome icon from a closed set of names; decorative unless `label` is given. */
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
