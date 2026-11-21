import { cn } from '../../../lib/cn';
import styles from './IconButton.module.css';

export interface IconButtonProps {
  /** Required: icon-only controls have no visible text, so this becomes the aria-label. */
  label: string;
  /** The icon element to render inside the button. */
  children: React.ReactNode;
  disabled?: boolean;
  /** HTML button type attribute. Defaults to 'button'. */
  type?: 'button' | 'submit' | 'reset';
  onClick?: React.MouseEventHandler<HTMLButtonElement>;
  className?: string;
}

/** Circular icon-only button; `label` becomes its aria-label. */
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
