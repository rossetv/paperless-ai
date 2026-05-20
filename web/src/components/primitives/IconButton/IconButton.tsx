import { cn } from '../../../lib/cn';
import styles from './IconButton.module.css';

export interface IconButtonProps {
  /**
   * Accessible label for the button — required because icon-only controls have
   * no visible text. This becomes the aria-label attribute.
   */
  label: string;
  /** The icon element to render inside the button. */
  children: React.ReactNode;
  /** Whether the button is non-interactive. */
  disabled?: boolean;
  /** HTML button type attribute. Defaults to 'button'. */
  type?: 'button' | 'submit' | 'reset';
  /** Click handler. */
  onClick?: React.MouseEventHandler<HTMLButtonElement>;
  /** Additional class names to merge. */
  className?: string;
}

/**
 * Icon-only button primitive.
 *
 * MUST receive a `label` prop — it is forwarded as aria-label so the control
 * is accessible to screen readers and assistive technology. No visible text is
 * rendered; the icon conveys meaning visually.
 *
 * Circular by default (Media Control style per DESIGN.md §4), with the accent
 * focus ring on keyboard activation.
 */
export function IconButton({
  label,
  children,
  disabled = false,
  type = 'button',
  onClick,
  className,
}: IconButtonProps): React.ReactElement {
  const classes = cn(styles['icon-button'], className);

  return (
    <button
      type={type}
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
      className={classes}
    >
      {children}
    </button>
  );
}
