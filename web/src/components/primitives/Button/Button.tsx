import { cn } from '../../../lib/cn';
import styles from './Button.module.css';

/** Visual variant — primary is accent-filled, secondary is outlined. */
export type ButtonVariant = 'primary' | 'secondary';

/** Size scale — default renders at the standard button token size. */
export type ButtonSize = 'default' | 'small';

export interface ButtonProps {
  /** Visual treatment. Defaults to 'primary'. */
  variant?: ButtonVariant;
  /** Size scale. Defaults to 'default'. */
  size?: ButtonSize;
  /** Whether the button is non-interactive. */
  disabled?: boolean;
  /** HTML button type attribute. Defaults to 'button'. */
  type?: 'button' | 'submit' | 'reset';
  /** Click handler. */
  onClick?: React.MouseEventHandler<HTMLButtonElement>;
  /** Button label content. */
  children: React.ReactNode;
  /** Additional class names to merge. */
  className?: string;
}

/**
 * Generic primitive button.
 *
 * Uses semantic <button> for full keyboard accessibility.
 * Reads all design values from CSS tokens — no hardcoded colours or sizes.
 * Two variants: primary (accent-filled CTA) and secondary (outlined).
 */
export function Button({
  variant = 'primary',
  size = 'default',
  disabled = false,
  type = 'button',
  onClick,
  children,
  className,
}: ButtonProps): React.ReactElement {
  const classes = cn(
    styles['button'],
    variant === 'primary' ? styles['primary'] : styles['secondary'],
    size === 'small' ? styles['small'] : styles['default-size'],
    className,
  );

  return (
    <button
      type={type}
      disabled={disabled}
      onClick={onClick}
      className={classes}
    >
      {children}
    </button>
  );
}
