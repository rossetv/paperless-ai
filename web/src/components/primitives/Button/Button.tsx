import { cn } from '../../../lib/cn';
import styles from './Button.module.css';

/**
 * Visual variant.
 * - primary: accent-filled CTA.
 * - secondary: outlined.
 * - destructive: danger-red fill for irreversible actions (delete, rebuild).
 * - ghost: no border or background — low-prominence action (e.g. modal cancel).
 */
export type ButtonVariant = 'primary' | 'secondary' | 'destructive' | 'ghost';

export type ButtonSize = 'default' | 'small';

export interface ButtonProps {
  /** Visual treatment. Defaults to 'primary'. */
  variant?: ButtonVariant;
  /** Size scale. Defaults to 'default'. */
  size?: ButtonSize;
  disabled?: boolean;
  /** HTML button type attribute. Defaults to 'button'. */
  type?: 'button' | 'submit' | 'reset';
  onClick?: React.MouseEventHandler<HTMLButtonElement>;
  children: React.ReactNode;
  className?: string;
  /** Accessible label override for icon-only or contextually unique buttons. */
  'aria-label'?: string;
}

/** Generic button rendered as a native `<button>`. */
export function Button({
  variant = 'primary',
  size = 'default',
  disabled = false,
  type = 'button',
  onClick,
  children,
  className,
  'aria-label': ariaLabel,
}: ButtonProps): React.ReactElement {
  const variantClass =
    variant === 'primary' ? styles['primary']
    : variant === 'destructive' ? styles['destructive']
    : variant === 'ghost' ? styles['ghost']
    : styles['secondary'];

  const classes = cn(
    styles['button'],
    variantClass,
    size === 'small' ? styles['small'] : styles['default-size'],
    className,
  );

  return (
    <button
      type={type}
      disabled={disabled}
      onClick={onClick}
      className={classes}
      aria-label={ariaLabel}
    >
      {children}
    </button>
  );
}
