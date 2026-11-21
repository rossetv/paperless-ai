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
  children: React.ReactNode;
  className?: string;
}

/**
 * Compact tag/filter chip. With `onClick` the root is a toggle `<button>`;
 * without it, a plain `<span>`. `onRemove` adds a labelled dismiss button.
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
  // 'Remove' for non-string children with no explicit removeLabel.
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
      <span aria-hidden="true">×</span>
    </button>
  ) : null;

  // With both onClick and onRemove, the remove control must be a sibling of the
  // toggle button, not nested in it (button-in-button is invalid HTML).
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
