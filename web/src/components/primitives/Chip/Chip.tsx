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

  // Derive a default accessible label from string children.
  // Callers with non-string children MUST supply removeLabel explicitly.
  const computedRemoveLabel =
    removeLabel ??
    (typeof children === 'string' ? `Remove ${children}` : undefined);

  const inner = (
    <>
      <span className={styles['chip-label']}>{children}</span>
      {onRemove !== undefined && (
        <button
          type="button"
          className={styles['chip-remove']}
          aria-label={computedRemoveLabel}
          onClick={onRemove}
        >
          {/* × character — visually communicates dismissal without a dependency */}
          <span aria-hidden="true">×</span>
        </button>
      )}
    </>
  );

  if (onClick !== undefined) {
    return (
      <button
        type="button"
        className={classes}
        onClick={onClick}
        aria-pressed={selected}
      >
        {inner}
      </button>
    );
  }

  return (
    <span className={classes}>
      {inner}
    </span>
  );
}
