import { cn } from '../../../lib/cn';
import styles from './RoleBadge.module.css';

/** `service` is a non-human identity (an API key or daemon account), not a sign-in role. */
export type Role = 'admin' | 'member' | 'readonly' | 'service';

export interface RoleBadgeProps {
  role: Role;
  className?: string;
}

/** Human-readable labels — `readonly` becomes "Read-only", others title-case. */
const LABELS: Record<Role, string> = {
  admin: 'Admin',
  member: 'Member',
  readonly: 'Read-only',
  service: 'Service',
};

/** Coloured pill naming a user's role, with one status-colour pair per role. */
export function RoleBadge({ role, className }: RoleBadgeProps): React.ReactElement {
  return (
    <span className={cn(styles['badge'], styles[role], className)}>
      {LABELS[role]}
    </span>
  );
}
