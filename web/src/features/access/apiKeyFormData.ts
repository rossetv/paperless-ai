/** Form data shared by the API-key create and edit panels. */
import type { ApiScope } from '../../api/types';

/** The selectable scopes, with their human descriptions. */
export const SCOPES: { id: ApiScope; description: string }[] = [
  {
    id: 'api',
    description: 'REST endpoints under /api/* — search, facets, stats, reconcile.',
  },
  {
    id: 'mcp',
    description:
      'The MCP server at /mcp — semantic_search, keyword_search, fetch_documents, list_filters, deep_search.',
  },
  {
    id: 'admin',
    description: 'Manage users and other keys. Grant sparingly.',
  },
];

/** Expiry quick-pick options, in days. `null` means "never expires". */
export const EXPIRY_CHOICES: { label: string; days: number | null }[] = [
  { label: 'Never', days: null },
  { label: '7 days', days: 7 },
  { label: '30 days', days: 30 },
  { label: '90 days', days: 90 },
  { label: '365 days', days: 365 },
];

/** Convert a day-count to an ISO expiry timestamp, or null for "never". */
export function expiryIso(days: number | null): string | null {
  if (days === null) return null;
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString();
}
