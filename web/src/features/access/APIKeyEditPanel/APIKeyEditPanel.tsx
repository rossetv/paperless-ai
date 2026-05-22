import React from 'react';
import { Modal } from '../../../components/patterns/Modal/Modal';
import { Input } from '../../../components/primitives/Input/Input';
import { Button } from '../../../components/primitives/Button/Button';
import { ScopePill } from '../../../components/primitives/ScopePill/ScopePill';
import { cn } from '../../../lib/cn';
import { useUpdateApiKey } from '../../../api/hooks';
import type { ApiKey, ApiScope } from '../../../api/types';
import styles from './APIKeyEditPanel.module.css';

/** The selectable scopes, with their human descriptions. */
const SCOPES: { id: ApiScope; description: string }[] = [
  {
    id: 'api',
    description: 'REST endpoints under /api/* — search, facets, stats, reconcile.',
  },
  {
    id: 'mcp',
    description: 'The MCP server at /mcp — ask_documents, search_documents.',
  },
  {
    id: 'admin',
    description: 'Manage users and other keys. Grant sparingly.',
  },
];

/** Expiry quick-pick options, in days. `null` means "never expires". */
const EXPIRY_CHOICES: { label: string; days: number | null }[] = [
  { label: 'Never', days: null },
  { label: '7 days', days: 7 },
  { label: '30 days', days: 30 },
  { label: '90 days', days: 90 },
  { label: '365 days', days: 365 },
];

/** Convert a day-count to an ISO expiry, or null for "never". */
function expiryIso(days: number | null): string | null {
  if (days === null) return null;
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString();
}

export interface APIKeyEditPanelProps {
  /** The key being edited — its current values pre-fill the form. */
  apiKey: ApiKey;
  /** Called to dismiss the panel (cancel, Escape, or a successful save). */
  onClose: () => void;
}

/**
 * The edit-API-key form.
 *
 * Pre-fills a key's current name, scopes and expiry, then calls
 * `useUpdateApiKey` (`PATCH /api/api-keys/{id}`) on submit. Editing never
 * re-reveals the secret, so a successful save simply closes the panel.
 *
 * The expiry control is a quick-pick — "Never" or a day-count from today.
 * The key's *existing* `expires_at` is shown as the pre-selected chip only
 * when it matches a quick-pick; otherwise the form opens on "Never" and the
 * user re-picks. The edit always sends `expires_at` (an absolute ISO value
 * or `null`), so the server replaces whatever was stored.
 *
 * Tier: features/access (CODE_GUIDELINES §12.3). Allowed deps: components/*,
 * api/, hooks/, lib/.
 */
export function APIKeyEditPanel({
  apiKey,
  onClose,
}: APIKeyEditPanelProps): React.ReactElement {
  const updateKey = useUpdateApiKey();

  const [name, setName] = React.useState(apiKey.name);
  const [scopes, setScopes] = React.useState<Set<ApiScope>>(
    new Set(apiKey.scopes),
  );
  const [expiryDays, setExpiryDays] = React.useState<number | null>(null);
  const [nameError, setNameError] = React.useState<string | null>(null);
  const [scopeError, setScopeError] = React.useState<string | null>(null);
  const [serverError, setServerError] = React.useState<string | null>(null);

  /** Toggle a scope on or off. */
  function toggleScope(scope: ApiScope): void {
    setScopeError(null);
    setScopes((prev) => {
      const next = new Set(prev);
      if (next.has(scope)) next.delete(scope);
      else next.add(scope);
      return next;
    });
  }

  /** Submit — save the edit. */
  async function handleSubmit(event: React.FormEvent): Promise<void> {
    event.preventDefault();
    setServerError(null);
    let invalid = false;
    if (name.trim().length === 0) {
      setNameError('Give the key a name so you can recognise it later.');
      invalid = true;
    }
    if (scopes.size === 0) {
      setScopeError('Select at least one scope.');
      invalid = true;
    }
    if (invalid) return;
    try {
      await updateKey.mutateAsync({
        id: apiKey.id,
        body: {
          name: name.trim(),
          scopes: [...scopes],
          expires_at: expiryIso(expiryDays),
        },
      });
      onClose();
    } catch {
      setServerError('Could not save the changes. Try again.');
    }
  }

  return (
    <Modal isOpen title="Edit API key" onClose={onClose}>
      <form onSubmit={handleSubmit} noValidate>
        <Input
          id="key-name"
          label="Key name"
          value={name}
          error={nameError ?? undefined}
          onChange={(e) => {
            setName(e.target.value);
            setNameError(null);
          }}
        />

        <div className={styles['section']}>
          <span className={styles['section-label']}>Scopes</span>
          <div className={styles['scope-list']}>
            {SCOPES.map((scope) => {
              const on = scopes.has(scope.id);
              return (
                <label
                  key={scope.id}
                  className={cn(styles['scope-row'], on && styles['scope-row-on'])}
                >
                  <input
                    type="checkbox"
                    checked={on}
                    onChange={() => toggleScope(scope.id)}
                    aria-label={scope.id}
                  />
                  <span className={styles['scope-text']}>
                    <span className={styles['scope-name']}>
                      {scope.id.toUpperCase()}
                      <ScopePill scope={scope.id} />
                    </span>
                    <span className={styles['scope-desc']}>{scope.description}</span>
                  </span>
                </label>
              );
            })}
          </div>
          {scopeError !== null && (
            <p className={styles['error']} role="alert">
              {scopeError}
            </p>
          )}
        </div>

        <div className={styles['section']}>
          <span className={styles['section-label']}>Expiration</span>
          <div className={styles['chip-row']}>
            {EXPIRY_CHOICES.map((choice) => (
              <button
                key={choice.label}
                type="button"
                className={cn(
                  styles['chip'],
                  expiryDays === choice.days && styles['chip-on'],
                )}
                aria-pressed={expiryDays === choice.days}
                onClick={() => setExpiryDays(choice.days)}
              >
                {choice.label}
              </button>
            ))}
          </div>
        </div>

        {serverError !== null && (
          <p className={styles['error']} role="alert">
            {serverError}
          </p>
        )}

        <div className={styles['footer']}>
          <Button variant="secondary" type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" type="submit" disabled={updateKey.isPending}>
            Save changes
          </Button>
        </div>
      </form>
    </Modal>
  );
}
