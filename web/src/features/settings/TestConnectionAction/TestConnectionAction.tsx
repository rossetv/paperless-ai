import React from 'react';
import { Button } from '../../../components/primitives/Button/Button';
import { useTestConnection } from '../../../api/hooks';
import styles from './TestConnectionAction.module.css';

export interface TestConnectionActionProps {
  /** The current draft Paperless URL. */
  url: string;
  /** The current draft Paperless token — may be a mask (see `tokenIsMasked`). */
  token: string;
  /**
   * True when `token` is the server-side mask, not a real value the user
   * typed. When true the probe sends an empty token and the backend uses the
   * stored secret; when false the draft token is sent as-is.
   */
  tokenIsMasked: boolean;
}

/**
 * The Paperless "Test connection" action — a ghost button + status dot
 * designed for use in a `SettingsCard` `headerActions` slot.
 *
 * Probes `POST /api/settings/test-connection` with the live draft URL/token
 * so the user can verify a connection before saving. The result is shown
 * inline as a status dot + short label.
 *
 * Tier: features/ — calls a hook and composes primitives.
 */
export function TestConnectionAction({
  url,
  token,
  tokenIsMasked,
}: TestConnectionActionProps): React.ReactElement {
  const probe = useTestConnection();

  const runTest = (): void => {
    probe.mutate({
      paperless_url: url,
      paperless_token: tokenIsMasked ? '' : token,
    });
  };

  const statusClass = (() => {
    if (!probe.isSuccess && !probe.isError) return styles['conn-untested'];
    if (probe.isError) return styles['conn-err'];
    return probe.data.ok ? styles['conn-ok'] : styles['conn-err'];
  })();

  const statusLabel = (() => {
    if (probe.isPending) return 'Testing…';
    if (probe.isError) return 'Error';
    if (probe.isSuccess) {
      if (probe.data.ok) {
        const count = probe.data.document_count;
        return count !== undefined && count !== null
          ? `${count.toLocaleString()} docs`
          : 'Connected';
      }
      return probe.data.detail ?? 'Rejected';
    }
    return 'Untested';
  })();

  return (
    <div className={styles['action']}>
      <span className={styles['conn']}>
        <span className={`${styles['conn-dot']!} ${statusClass}`} />
        <span className={styles['conn-label']}>{statusLabel}</span>
      </span>
      <Button
        variant="secondary"
        size="small"
        disabled={probe.isPending}
        onClick={runTest}
      >
        {probe.isPending ? 'Testing…' : 'Run test'}
      </Button>
    </div>
  );
}
