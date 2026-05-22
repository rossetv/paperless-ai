import React from 'react';
import { Modal } from '../../../components/patterns/Modal/Modal';
import { Input } from '../../../components/primitives/Input/Input';
import { Button } from '../../../components/primitives/Button/Button';
import { ScopePill } from '../../../components/primitives/ScopePill/ScopePill';
import { cn } from '../../../lib/cn';
import { useCreateApiKey } from '../../../api/hooks';
import type { ApiScope } from '../../../api/types';
import styles from './APIKeyCreatePanel.module.css';

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

export interface APIKeyCreatePanelProps {
  /** Called to dismiss the panel (cancel, Escape, or Done after a mint). */
  onClose: () => void;
}

/**
 * The create-API-key form, with a one-time secret reveal.
 *
 * The form collects a name, scopes and expiry, then calls `useCreateApiKey`.
 * There is no owner field — an API key is always owned by the caller who
 * creates it (the backend hard-wires `owner_user_id = caller.id`). On success
 * the form is replaced by a reveal panel that shows the full `sk-pls-…`
 * secret exactly once — it is held in component state and discarded when the
 * modal closes. The secret is never re-fetchable.
 *
 * Tier: features/access (CODE_GUIDELINES §12.3). Allowed deps: components/*,
 * api/, hooks/, lib/.
 */
export function APIKeyCreatePanel({
  onClose,
}: APIKeyCreatePanelProps): React.ReactElement {
  const createKey = useCreateApiKey();

  const [name, setName] = React.useState('');
  const [scopes, setScopes] = React.useState<Set<ApiScope>>(new Set(['api']));
  const [expiryDays, setExpiryDays] = React.useState<number | null>(null);
  const [nameError, setNameError] = React.useState<string | null>(null);
  const [scopeError, setScopeError] = React.useState<string | null>(null);
  const [serverError, setServerError] = React.useState<string | null>(null);
  // Once set, the form is replaced by the reveal panel.
  const [secret, setSecret] = React.useState<string | null>(null);
  const [copied, setCopied] = React.useState(false);

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

  /** Submit — mint the key. */
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
      const result = await createKey.mutateAsync({
        name: name.trim(),
        scopes: [...scopes],
        expires_at: expiryIso(expiryDays),
      });
      setSecret(result.secret);
    } catch {
      setServerError('Could not create the key. Try again.');
    }
  }

  /** Copy the revealed secret to the clipboard. */
  async function handleCopy(): Promise<void> {
    if (secret === null) return;
    try {
      await navigator.clipboard.writeText(secret);
      setCopied(true);
    } catch {
      // Clipboard denied — leave the value visible for a manual copy.
      setCopied(false);
    }
  }

  // ── Reveal panel — shown once the key is minted. ──
  if (secret !== null) {
    return (
      <Modal isOpen title="API key created" onClose={onClose}>
        <div className={styles['reveal']}>
          <p className={styles['reveal-note']}>
            Copy this key now — it is shown <strong>once</strong>. After you
            close this panel only the prefix is stored and the full key cannot
            be recovered.
          </p>
          <div className={styles['secret-box']}>
            <code className={styles['secret-value']}>{secret}</code>
            <Button variant="secondary" type="button" onClick={() => void handleCopy()}>
              {copied ? 'Copied' : 'Copy'}
            </Button>
          </div>
          <div className={styles['footer']}>
            <Button variant="primary" type="button" onClick={onClose}>
              Done
            </Button>
          </div>
        </div>
      </Modal>
    );
  }

  // ── Create form. ──
  return (
    <Modal isOpen title="Create API key" onClose={onClose}>
      <form onSubmit={handleSubmit} noValidate>
        <div className={styles['grid']}>
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
        </div>

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
          <Button variant="primary" type="submit" disabled={createKey.isPending}>
            Generate key
          </Button>
        </div>
      </form>
    </Modal>
  );
}
