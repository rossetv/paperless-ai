import { cn } from '../../../lib/cn';
import styles from './ScopePill.module.css';

/** The API-key scopes a ScopePill can render. */
export type ApiScope = 'api' | 'mcp' | 'admin';

export interface ScopePillProps {
  scope: ApiScope;
  className?: string;
}

/** Display labels — `api`/`mcp` uppercase, `admin` title-case. */
const LABELS: Record<ApiScope, string> = {
  api: 'API',
  mcp: 'MCP',
  admin: 'Admin',
};

/** Monospace pill naming an API-key scope, coloured per scope. */
export function ScopePill({ scope, className }: ScopePillProps): React.ReactElement {
  return (
    <span className={cn(styles['pill'], styles[scope], className)}>
      {LABELS[scope]}
    </span>
  );
}
