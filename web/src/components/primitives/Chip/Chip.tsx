import stylesRaw from './Chip.module.css';

// CSS Modules return a string-indexed object; bracket notation is required
// under noPropertyAccessFromIndexSignature (tsconfig strict mode).
const styles = stylesRaw as Record<string, string>;

export interface ChipProps {
  /** Whether this chip is in the active/selected state. Defaults to false. */
  selected?: boolean;
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
 * Renders as a <span> container — not itself interactive.
 * When `onRemove` is provided, a <button> dismiss control is rendered inside
 * with an accessible aria-label so screen readers announce the action.
 *
 * The remove button carries the accent focus ring for keyboard operability.
 */
export function Chip({
  selected = false,
  onRemove,
  removeLabel,
  children,
  className,
}: ChipProps): React.ReactElement {
  const classes = [
    styles['chip'],
    selected ? styles['selected'] : undefined,
    className,
  ]
    .filter(Boolean)
    .join(' ');

  // Derive a default accessible label from string children.
  // Callers with non-string children MUST supply removeLabel explicitly.
  const computedRemoveLabel =
    removeLabel ??
    (typeof children === 'string' ? `Remove ${children}` : undefined);

  return (
    <span className={classes}>
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
    </span>
  );
}
