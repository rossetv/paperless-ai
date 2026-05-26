import React from 'react';
import { cn } from '../../../lib/cn';
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
 * The Paperless "Test connection" action — a status pill + ghost button
 * designed for use in a `SettingsCard` `headerActions` slot.
 *
 * Visually matches mediaman's `.conn` + `.btn-test` pair: a coloured dot with
 * a glow shadow, a short status label, and a pill-shaped ghost button with a
 * hairline border.
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

  const tone: 'ok' | 'err' | 'untested' = (() => {
    if (probe.isPending) return 'untested';
    if (probe.isError) return 'err';
    if (probe.isSuccess) return probe.data.ok ? 'ok' : 'err';
    return 'untested';
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
      return 'Rejected';
    }
    return 'Untested';
  })();

  return (
    <div className={styles['action']}>
      <span
        className={cn(
          styles['conn'],
          tone === 'ok' && styles['conn-ok'],
          tone === 'err' && styles['conn-err'],
          tone === 'untested' && styles['conn-untested'],
        )}
        title={probe.isError ? 'Could not reach the server — check the URL.' :
          probe.isSuccess && !probe.data.ok ? probe.data.detail ?? '' : undefined}
      >
        <span className={styles['conn-dot']} />
        <span className={styles['conn-label']}>{statusLabel}</span>
      </span>
      <button
        type="button"
        className={styles['btn-test']}
        disabled={probe.isPending}
        onClick={runTest}
      >
        {probe.isPending ? 'Testing…' : 'Test'}
      </button>
    </div>
  );
}
