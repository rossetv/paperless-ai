import { cn } from '../../../lib/cn';
import styles from './ScopePill.module.css';

/** The API-key scopes a ScopePill can render. */
export type ApiScope = 'api' | 'mcp' | 'admin';

export interface ScopePillProps {
  /** The scope to display. */
  scope: ApiScope;
  /** Additional class names to merge. */
  className?: string;
}

/** Display labels — `api`/`mcp` uppercase, `admin` title-case. */
const LABELS: Record<ApiScope, string> = {
  api: 'API',
  mcp: 'MCP',
  admin: 'Admin',
};

/**
 * Small monospace pill naming an API-key scope.
 *
 * Renders a non-interactive `<span>`. Each scope maps to a distinct
 * semantic colour. Used in the API-key create panel and the keys table.
 *
 * Tier: components/primitives (CODE_GUIDELINES §12.3). Allowed deps: lib/.
 */
export function ScopePill({ scope, className }: ScopePillProps): React.ReactElement {
  return (
    <span className={cn(styles['pill'], styles[scope], className)}>
      {LABELS[scope]}
    </span>
  );
}
