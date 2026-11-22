import React from 'react';
import { cn } from '../../../lib/cn';
import { Avatar } from '../../primitives/Avatar/Avatar';
import styles from './UserMenu.module.css';

export interface UserMenuProps {
  /** 1–2 character initials shown in the avatar trigger. */
  initials: string;
  /** The user's display name. When `null`, `username` is shown instead. */
  displayName: string | null;
  /**
   * The user's username — the fallback header label when `displayName` is
   * `null`. Optional only because some callers always have a display name;
   * supply it whenever `displayName` can be `null`.
   */
  username?: string;
  /** The user's email, shown under the name. May be `null` (then omitted). */
  email: string | null;
  /** Called on "Sign out"; the caller performs the logout and routing. */
  onSignOut: () => void;
  /** Background colour for the avatar. Defaults to the neutral grey gradient. */
  avatarColour?: string;
  className?: string;
}

const DEFAULT_AVATAR_COLOUR = 'var(--gradient-avatar-default)';

/**
 * Account dropdown: an `Avatar` trigger opening a menu with a name/email header
 * and a "Sign out" item. Focus moves into the menu on open; Arrow keys, Home and End move between items,
 * and Escape or a pick returns focus to the trigger. Also closes on Tab or an
 * outside pointer-down.
 */
export function UserMenu({
  initials,
  displayName,
  username,
  email,
  onSignOut,
  avatarColour = DEFAULT_AVATAR_COLOUR,
  className,
}: UserMenuProps): React.ReactElement {
  const [open, setOpen] = React.useState(false);
  const rootRef = React.useRef<HTMLDivElement>(null);
  const triggerRef = React.useRef<HTMLButtonElement>(null);
  const menuRef = React.useRef<HTMLDivElement>(null);

  // Close on outside pointer-down, only while open.
  React.useEffect(() => {
    if (!open) return undefined;

    function handlePointerDown(event: MouseEvent): void {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }

    document.addEventListener('mousedown', handlePointerDown);
    return () => document.removeEventListener('mousedown', handlePointerDown);
  }, [open]);

  // Move focus into the menu on open.
  React.useEffect(() => {
    if (open) {
      menuRef.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus();
    }
  }, [open]);

  function handleKeyDown(event: React.KeyboardEvent): void {
    if (!open) return;
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      setOpen(false);
      triggerRef.current?.focus();
      return;
    }
    if (event.key === 'Tab') {
      // Focus the trigger before the menu unmounts so the browser's Tab moves on from it.
      triggerRef.current?.focus();
      setOpen(false);
      return;
    }
    const items = Array.from(
      menuRef.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? [],
    );
    const current = items.indexOf(document.activeElement as HTMLElement);
    if (items.length === 0 || current === -1) return;
    let next: number;
    if (event.key === 'ArrowDown') next = (current + 1) % items.length;
    else if (event.key === 'ArrowUp') next = (current - 1 + items.length) % items.length;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = items.length - 1;
    else return;
    event.preventDefault();
    items[next]?.focus();
  }

  function handleSignOut(): void {
    setOpen(false);
    triggerRef.current?.focus();
    onSignOut();
  }

  const headerName = displayName ?? username ?? 'Account';

  return (
    <div ref={rootRef} className={cn(styles['root'], className)} onKeyDown={handleKeyDown}>
      <button
        ref={triggerRef}
        type="button"
        className={styles['trigger']}
        aria-label="Account menu"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((prev) => !prev)}
      >
        <Avatar initials={initials} colour={avatarColour} size={26} />
      </button>

      {open && (
        <div ref={menuRef} className={styles['dropdown']} role="menu">
          <div className={styles['header']}>
            <span className={styles['name']}>{headerName}</span>
            {email !== null && email !== '' && (
              <span className={styles['email']}>{email}</span>
            )}
          </div>
          <hr className={styles['divider']} />
          <button
            type="button"
            role="menuitem"
            tabIndex={-1}
            className={styles['item']}
            onClick={handleSignOut}
          >
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}
