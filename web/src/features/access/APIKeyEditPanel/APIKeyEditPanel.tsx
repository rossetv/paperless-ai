import React from 'react';
import { Modal } from '../../../components/patterns/Modal/Modal';
import { Input } from '../../../components/primitives/Input/Input';
import { Button } from '../../../components/primitives/Button/Button';
import { useUpdateApiKey } from '../../../api/hooks';
import type { ApiKey, ApiScope } from '../../../api/types';
import { expiryIso } from '../apiKeyFormData';
import { ScopeChecklist } from '../ScopeChecklist/ScopeChecklist';
import { ExpiryChips } from '../ExpiryChips/ExpiryChips';
import shared from '../ScopeChecklist/ScopeChecklist.module.css';

export interface APIKeyEditPanelProps {
  /** The key being edited — its current values pre-fill the form. */
  apiKey: ApiKey;
  /** Called to dismiss the panel (cancel, Escape, or a successful save). */
  onClose: () => void;
}

/**
 * The edit-API-key form.
 *
 * Pre-fills a key's current name and scopes, then calls
 * `useUpdateApiKey` (`PATCH /api/api-keys/{id}`) on submit. Editing never
 * re-reveals the secret, so a successful save simply closes the panel.
 *
 * The expiry control is a quick-pick — "Never" or a day-count from today.
 * Crucially, `expires_at` is **only included in the PATCH body when the
 * user explicitly selects a chip** — otherwise the field is omitted so the
 * server leaves the existing expiry unchanged. This prevents a silent
 * credential-lifetime downgrade when a user edits only the key name.
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
  // expiryDays is the user's chosen day-count; null = "Never".
  const [expiryDays, setExpiryDays] = React.useState<number | null>(null);
  // expiryTouched tracks whether the user has explicitly clicked a chip.
  // When false the expiry field is omitted from the PATCH body so the server
  // leaves the existing expires_at unchanged.
  const [expiryTouched, setExpiryTouched] = React.useState(false);
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

  /** Select an expiry chip — marks the field as explicitly touched. */
  function selectExpiry(days: number | null): void {
    setExpiryDays(days);
    setExpiryTouched(true);
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
          // Only include expires_at when the user explicitly changed it.
          // Omitting the field leaves the server-side value unchanged.
          ...(expiryTouched ? { expires_at: expiryIso(expiryDays) } : {}),
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

        <ScopeChecklist
          selectedScopes={scopes}
          onToggle={toggleScope}
          error={scopeError}
        />

        <ExpiryChips
          selectedDays={expiryDays}
          touched={expiryTouched}
          onChange={selectExpiry}
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
          <Button variant="primary" type="submit" disabled={updateKey.isPending}>
            Save changes
          </Button>
        </div>
      </form>
    </Modal>
  );
}
