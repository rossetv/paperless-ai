import { cn } from '../../../lib/cn';
import styles from './Chip.module.css';

export interface ChipProps {
  /** Whether this chip is in the active/selected state. Defaults to false. */
  selected?: boolean;
  /**
   * When provided, the chip root becomes an interactive <button> that toggles
   * selection. The chip gains a focus ring and is keyboard-operable (Enter/Space).
   */
  onClick?: () => void;
  /**
   * When provided, a dismiss button is rendered inside the chip.
   * Called when the user clicks or activates (Enter/Space) the remove control.
   */
  onRemove?: () => void;
  /**
   * Accessible label for the remove button.
   * Defaults to "Remove {children}" if children is a string;
   * callers must supply this for non-string children.
   */
  removeLabel?: string;
  /** Chip label content. */
  children: React.ReactNode;
  /** Additional class names to merge. */
  className?: string;
}

/**
 * Compact tag/filter chip.
 *
 * When `onClick` is provided, the chip root renders as a <button> so it is
 * keyboard-operable (Enter/Space) and participates in the tab order. The
 * accent focus ring applies. This is the interactive toggle mode used by
 * FilterControls.
 *
 * Without `onClick`, renders as a <span> container — not itself interactive.
 *
 * When `onRemove` is provided, a <button> dismiss control is rendered inside
 * with an accessible aria-label so screen readers announce the action.
 *
 * The remove button carries the accent focus ring for keyboard operability.
 */
export function Chip({
  selected = false,
  onClick,
  onRemove,
  removeLabel,
  children,
  className,
}: ChipProps): React.ReactElement {
  const classes = cn(
    styles['chip'],
    selected ? styles['selected'] : undefined,
    onClick !== undefined ? styles['chip-interactive'] : undefined,
    className,
  );

  // Derive a default accessible label from string children; fall back to
  // 'Remove' for non-string children with no explicit removeLabel (FE-35).
  const computedRemoveLabel =
    removeLabel ??
    (typeof children === 'string' ? `Remove ${children}` : 'Remove');

  const removeButton = onRemove !== undefined ? (
    <button
      type="button"
      className={styles['chip-remove']}
      aria-label={computedRemoveLabel}
      onClick={onRemove}
    >
      {/* × character — visually communicates dismissal without a dependency */}
      <span aria-hidden="true">×</span>
    </button>
  ) : null;

  // When the root is a <button> (onClick) AND onRemove is supplied, the remove
  // control must be a sibling — not nested — to avoid invalid button-in-button
  // HTML (FE-34). Wrap both in a span so the pair can still share the chip
  // visual class from the inner toggle button.
  if (onClick !== undefined) {
    if (removeButton !== null) {
      return (
        <span className={cn(styles['chip-outer'], className)}>
          <button
            type="button"
            className={cn(styles['chip-inner-toggle'], selected ? styles['selected'] : undefined)}
            onClick={onClick}
            aria-pressed={selected}
          >
            <span className={styles['chip-label']}>{children}</span>
          </button>
          {removeButton}
        </span>
      );
    }

    return (
      <button
        type="button"
        className={classes}
        onClick={onClick}
        aria-pressed={selected}
      >
        <span className={styles['chip-label']}>{children}</span>
      </button>
    );
  }

  return (
    <span className={classes}>
      <span className={styles['chip-label']}>{children}</span>
      {removeButton}
    </span>
  );
}
