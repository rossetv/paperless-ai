import React from 'react';
import { ScopePill } from '../../../components/primitives/ScopePill/ScopePill';
import { cn } from '../../../lib/cn';
import type { ApiScope } from '../../../api/types';
import { SCOPES } from '../apiKeyFormData';
import styles from './ScopeChecklist.module.css';

export interface ScopeChecklistProps {
  /** The currently selected scopes. */
  selectedScopes: Set<ApiScope>;
  /** Called with the toggled scope when a checkbox is changed. */
  onToggle: (scope: ApiScope) => void;
  /** Validation error to display beneath the list; null hides the error. */
  error: string | null;
}

/**
 * Renders the scope checkbox list shared by APIKeyCreatePanel and
 * APIKeyEditPanel. Stateless — the parent owns `selectedScopes` and `error`.
 *
 * Tier: features/access. Allowed deps: components/*, api/types, lib/.
 */
export function ScopeChecklist({
  selectedScopes,
  onToggle,
  error,
}: ScopeChecklistProps): React.ReactElement {
  return (
    <div className={styles['section']}>
      <span className={styles['section-label']}>Scopes</span>
      <div className={styles['scope-list']}>
        {SCOPES.map((scope) => {
          const on = selectedScopes.has(scope.id);
          return (
            <label
              key={scope.id}
              className={cn(styles['scope-row'], on && styles['scope-row-on'])}
            >
              <input
                type="checkbox"
                checked={on}
                onChange={() => onToggle(scope.id)}
              />
              <span className={styles['scope-text']}>
                <span className={styles['scope-name']}>
                  <ScopePill scope={scope.id} />
                </span>
                <span className={styles['scope-desc']}>{scope.description}</span>
              </span>
            </label>
          );
        })}
      </div>
      {error !== null && (
        <p className={styles['error']} role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
