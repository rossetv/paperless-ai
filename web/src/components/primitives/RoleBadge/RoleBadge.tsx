import { cn } from '../../../lib/cn';
import styles from './RoleBadge.module.css';

/**
 * The role values a RoleBadge can render.
 *
 * `admin` / `member` / `readonly` are the three human RBAC roles. `service`
 * is a non-human identity (an API key or a daemon account) shown in the
 * Users table — it is not a sign-in role.
 */
export type Role = 'admin' | 'member' | 'readonly' | 'service';

export interface RoleBadgeProps {
  /** The role to display. */
  role: Role;
  /** Additional class names to merge. */
  className?: string;
}

/** Human-readable labels — `readonly` becomes "Read-only", others title-case. */
const LABELS: Record<Role, string> = {
  admin: 'Admin',
  member: 'Member',
  readonly: 'Read-only',
  service: 'Service',
};

/**
 * Small semantic-coloured pill naming a user's role.
 *
 * Renders a non-interactive `<span>`. Each role maps to a distinct
 * status-colour token pair so roles are distinguishable at a glance in the
 * Users table. Carries no domain logic — the caller supplies the role.
 *
 * Tier: components/primitives (CODE_GUIDELINES §12.3). Allowed deps: lib/.
 */
export function RoleBadge({ role, className }: RoleBadgeProps): React.ReactElement {
  return (
    <span className={cn(styles['badge'], styles[role], className)}>
      {LABELS[role]}
    </span>
  );
}
