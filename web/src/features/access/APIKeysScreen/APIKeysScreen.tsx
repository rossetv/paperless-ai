import React from 'react';
import { SettingsLayout } from '../../../components/layout/SettingsLayout/SettingsLayout';
import { Table } from '../../../components/primitives/Table/Table';
import type { Column } from '../../../components/primitives/Table/Table';
import { Button } from '../../../components/primitives/Button/Button';
import { EmptyState } from '../../../components/patterns/EmptyState/EmptyState';
import { Spinner } from '../../../components/primitives/Spinner/Spinner';
import { ScopePill } from '../../../components/primitives/ScopePill/ScopePill';
import { cn } from '../../../lib/cn';
import { useApiKeys, useDeleteApiKey } from '../../../api/hooks';
import { useAuth } from '../../../hooks/useAuth';
import type { ApiKey } from '../../../api/types';
import { APIKeyCreatePanel } from '../APIKeyCreatePanel/APIKeyCreatePanel';
import { APIKeyEditPanel } from '../APIKeyEditPanel/APIKeyEditPanel';
import { formatShortDate } from '../../../lib/formatDate';
import styles from './APIKeysScreen.module.css';

/** The lifecycle state of a key, derived from its timestamps. */
type KeyState = 'active' | 'expired' | 'revoked';

/** Derive a key's state from `revoked_at` / `expires_at`. */
function keyStateOf(key: ApiKey): KeyState {
  if (key.revoked_at !== null) return 'revoked';
  if (key.expires_at !== null && new Date(key.expires_at).getTime() < Date.now()) {
    return 'expired';
  }
  return 'active';
}

/** Format the "last used" cell — a date, or a dash when never used. */
function formatLastUsed(iso: string | null): string {
  return iso === null ? 'Never used' : formatShortDate(iso);
}

/**
 * The expiry cell — "Never" for an open key, a date otherwise, prefixed with
 * "Expired" once the date is in the past.
 */
function ExpiryLabel({ keyRow }: { keyRow: ApiKey }): React.ReactElement {
  if (keyRow.expires_at === null) {
    return <span>Never</span>;
  }
  const state = keyStateOf(keyRow);
  if (state === 'expired') {
    return (
      <span className={styles['expiry-expired']}>
        Expired {formatShortDate(keyRow.expires_at)}
      </span>
    );
  }
  return <span>{formatShortDate(keyRow.expires_at)}</span>;
}

/**
 * The API-key management screen.
 *
 * Lists every key in a {@link Table}, derives each key's lifecycle state,
 * and offers a confirm-guarded revoke (active key) or delete (expired /
 * revoked key) — both via `useDeleteApiKey`, since the server decides which
 * applies. The {@link APIKeyCreatePanel} mints new keys and reveals the
 * secret once; the {@link APIKeyEditPanel} edits an existing key.
 *
 * Editing is owner-only on the server (`PATCH` returns 403 for a non-owner),
 * so the Edit affordance is shown only on an active key the signed-in caller
 * owns — `useAuth` supplies the caller's id. An admin viewing another user's
 * key sees Revoke but not Edit.
 *
 * Tier: features/access (CODE_GUIDELINES §12.3). Allowed deps: components/*,
 * api/, hooks/, lib/.
 */
export function APIKeysScreen(): React.ReactElement {
  const keysQuery = useApiKeys();
  const deleteKey = useDeleteApiKey();
  const { user: me } = useAuth();
  const [panelOpen, setPanelOpen] = React.useState(false);
  // The key currently open in the edit panel, or null when none.
  const [editingKey, setEditingKey] = React.useState<ApiKey | null>(null);
  // The id of the key currently awaiting a delete/revoke confirmation.
  const [confirmingId, setConfirmingId] = React.useState<number | null>(null);

  const keys = keysQuery.data?.keys ?? [];

  /** Run the delete/revoke for a key, then clear the confirm state. */
  async function handleDelete(id: number): Promise<void> {
    try {
      await deleteKey.mutateAsync(id);
    } finally {
      setConfirmingId(null);
    }
  }

  const columns: Column<ApiKey>[] = [
    {
      key: 'name',
      header: 'Name & key',
      render: (k) => {
        const state = keyStateOf(k);
        return (
          <div className={styles['key-cell']}>
            <span className={styles['key-name']}>
              {k.name}
              {state === 'expired' && (
                <span className={styles['expiry-expired']}>· expired</span>
              )}
              {state === 'revoked' && (
                <span className={styles['expiry-expired']}>· revoked</span>
              )}
            </span>
            <span className={styles['key-meta']}>
              <span>{k.key_prefix}••••••••••</span>
              <span className={styles['key-count']}>
                {k.request_count.toLocaleString()} requests · created{' '}
                {formatShortDate(k.created_at)}
              </span>
            </span>
          </div>
        );
      },
    },
    {
      key: 'scopes',
      header: 'Scopes',
      width: 'var(--width-col-badge)',
      render: (k) => (
        <div className={styles['scopes']}>
          {k.scopes.map((s) => (
            <ScopePill key={s} scope={s} />
          ))}
        </div>
      ),
    },
    {
      key: 'last',
      header: 'Last used',
      width: 'var(--width-col-date)',
      render: (k) => formatLastUsed(k.last_used_at),
    },
    {
      key: 'expires',
      header: 'Expires',
      width: 'var(--width-col-expiry)',
      render: (k) => <ExpiryLabel keyRow={k} />,
    },
    {
      key: 'actions',
      header: '',
      width: 'var(--width-col-expiry)',
      align: 'end',
      render: (k) => {
        const state = keyStateOf(k);
        const actionLabel = state === 'active' ? 'Revoke' : 'Delete';
        // Editing is owner-only — show Edit only on an active key the
        // signed-in caller owns (the server enforces this too).
        const canEdit = state === 'active' && k.owner_id === me?.id;
        return (
          <div className={styles['row-actions']}>
            {canEdit && (
              <Button
                variant="ghost"
                size="small"
                onClick={() => setEditingKey(k)}
              >
                Edit
              </Button>
            )}
            {confirmingId === k.id ? (
              <Button
                variant="destructive"
                size="small"
                disabled={deleteKey.isPending}
                onClick={() => void handleDelete(k.id)}
              >
                Confirm
              </Button>
            ) : (
              <Button
                variant="destructive"
                size="small"
                onClick={() => setConfirmingId(k.id)}
              >
                {actionLabel}
              </Button>
            )}
          </div>
        );
      },
    },
  ];

  return (
    <SettingsLayout
      title="API Keys"
      subtitle="Bearer tokens for the REST API, the MCP server, and external integrations."
      actions={
        <Button variant="primary" size="small" onClick={() => setPanelOpen(true)}>
          + New API key
        </Button>
      }
    >
      {keysQuery.isLoading ? (
        <Spinner size="large" label="Loading API keys…" />
      ) : keysQuery.isError ? (
        <div role="alert">
          <EmptyState
            icon="warning"
            message="Could not load API keys"
            description="Something went wrong fetching the key list. Refresh to try again."
          />
        </div>
      ) : keys.length === 0 ? (
        <EmptyState
          icon="key"
          message="No API keys yet"
          description="Create the first one to authenticate REST or MCP clients. The full key is shown once at creation — copy it then."
          action={
            <Button variant="primary" onClick={() => setPanelOpen(true)}>
              + New API key
            </Button>
          }
        />
      ) : (
        <>
          <Table
            columns={columns}
            rows={keys}
            getRowKey={(k) => k.id}
            isRowMuted={(k) => keyStateOf(k) !== 'active'}
            emptyMessage="No API keys match the current filter."
          />
          <p className={cn(styles['note'])}>
            The full key is shown once at creation. After that only the prefix
            is stored. {'Pass an active key as Authorization: Bearer <key>.'}
          </p>
        </>
      )}

      {panelOpen && (
        <APIKeyCreatePanel onClose={() => setPanelOpen(false)} />
      )}

      {editingKey !== null && (
        <APIKeyEditPanel
          apiKey={editingKey}
          onClose={() => setEditingKey(null)}
        />
      )}
    </SettingsLayout>
  );
}
