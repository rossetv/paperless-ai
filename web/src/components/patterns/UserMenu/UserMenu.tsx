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
 * and a "Sign out" item. Closes on Escape, an outside pointer-down, or a pick.
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

  // Close on outside pointer-down and on Escape, only while open.
  React.useEffect(() => {
    if (!open) return undefined;

    function handlePointerDown(event: MouseEvent): void {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    function handleKeyDown(event: KeyboardEvent): void {
      if (event.key === 'Escape') {
        setOpen(false);
      }
    }

    document.addEventListener('mousedown', handlePointerDown);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('mousedown', handlePointerDown);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [open]);

  function handleSignOut(): void {
    setOpen(false);
    onSignOut();
  }

  const headerName = displayName ?? username ?? 'Account';

  return (
    <div ref={rootRef} className={cn(styles['root'], className)}>
      <button
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
        <div className={styles['dropdown']} role="menu">
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
