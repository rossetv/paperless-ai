import React from 'react';
import { Row } from '../../../components/primitives/Row/Row';
import { Button } from '../../../components/primitives/Button/Button';
import { useTestConnection } from '../../../api/hooks';
import styles from './TestConnectionRow.module.css';

export interface TestConnectionRowProps {
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
 * The Paperless "Test connection" settings row.
 *
 * Probes `POST /api/settings/test-connection` with the live draft URL/token
 * so the user can verify a connection before saving. The result is shown
 * inline — a green count on success, a red message on a rejected probe or a
 * network failure.
 *
 * Tier: features/ — calls a hook and composes primitives.
 */
export function TestConnectionRow({
  url,
  token,
  tokenIsMasked,
}: TestConnectionRowProps): React.ReactElement {
  const probe = useTestConnection();

  const runTest = (): void => {
    // An empty token tells the backend to probe with the stored secret —
    // the user has not replaced the masked token.
    probe.mutate({
      paperless_url: url,
      paperless_token: tokenIsMasked ? '' : token,
    });
  };

  return (
    <Row
      label="Test connection"
      hint="Round-trips a GET against /api/documents/ to confirm the URL and token work."
      last
    >
      <div className={styles['control']}>
        <Button
          variant="secondary"
          size="small"
          disabled={probe.isPending}
          onClick={runTest}
        >
          {probe.isPending ? 'Testing…' : 'Run test'}
        </Button>
        {probe.isError && (
          <span className={`${styles['result']} ${styles['resultError']}`}>
            Could not reach the server — check the URL.
          </span>
        )}
        {probe.isSuccess && probe.data.ok && (
          <span className={`${styles['result']} ${styles['resultOk']}`}>
            ✓ Connected · {probe.data.document_count?.toLocaleString() ?? '0'} documents
          </span>
        )}
        {probe.isSuccess && !probe.data.ok && (
          <span className={`${styles['result']} ${styles['resultError']}`}>
            {probe.data.detail ?? 'The server rejected the connection.'}
          </span>
        )}
      </div>
    </Row>
  );
}
