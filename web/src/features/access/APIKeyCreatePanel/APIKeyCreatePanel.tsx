import React from 'react';
import { Modal } from '../../../components/patterns/Modal/Modal';
import { Input } from '../../../components/primitives/Input/Input';
import { Button } from '../../../components/primitives/Button/Button';
import { useCreateApiKey } from '../../../api/hooks';
import type { ApiScope } from '../../../api/types';
import { expiryIso } from '../apiKeyFormData';
import { ScopeChecklist } from '../ScopeChecklist/ScopeChecklist';
import { ExpiryChips } from '../ExpiryChips/ExpiryChips';
import styles from './APIKeyCreatePanel.module.css';
import shared from '../ScopeChecklist/ScopeChecklist.module.css';

export interface APIKeyCreatePanelProps {
  /** Called to dismiss the panel (cancel, Escape, or Done after a mint). */
  onClose: () => void;
}

// ── Reveal sub-component. ──
// rationale: The reveal panel and the create form share the same Modal but
// have no shared state after the secret is set — two logically distinct
// screens. Extracting this keeps each screen's JSX below ~60 lines and makes
// the one-time-view guarantee easy to audit.
interface RevealPanelProps {
  secret: string;
  onClose: () => void;
}

function RevealPanel({ secret, onClose }: RevealPanelProps): React.ReactElement {
  const [copied, setCopied] = React.useState(false);
  const [copyError, setCopyError] = React.useState(false);

  async function handleCopy(): Promise<void> {
    setCopied(false);
    try {
      await navigator.clipboard.writeText(secret);
      setCopied(true);
      setCopyError(false);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard access was denied — the user must copy the key manually.
      // Surface an error so they know the one-time secret was not captured
      // and the key text above is still selectable.
      setCopied(false);
      setCopyError(true);
    }
  }

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
        {copyError && (
          <p className={shared['error']} role="alert">
            Copy failed — your browser blocked clipboard access. Select the
            key text above and copy it manually before closing this panel.
          </p>
        )}
        <div className={shared['footer']}>
          <Button variant="primary" type="button" onClick={onClose}>
            Done
          </Button>
        </div>
      </div>
    </Modal>
  );
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

  if (secret !== null) {
    return <RevealPanel secret={secret} onClose={onClose} />;
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

        <ScopeChecklist
          selectedScopes={scopes}
          onToggle={toggleScope}
          error={scopeError}
        />

        <ExpiryChips
          selectedDays={expiryDays}
          touched={true}
          onChange={setExpiryDays}
        />

        {serverError !== null && (
          <p className={shared['error']} role="alert">
            {serverError}
          </p>
        )}

        <div className={shared['footer']}>
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
