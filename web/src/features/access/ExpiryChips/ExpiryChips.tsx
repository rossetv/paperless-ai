import React from 'react';
import { cn } from '../../../lib/cn';
import { EXPIRY_CHOICES } from '../apiKeyFormData';
import styles from '../ScopeChecklist/ScopeChecklist.module.css';

export interface ExpiryChipsProps {
  /** The currently selected day-count; null means "Never". */
  selectedDays: number | null;
  /**
   * Whether to highlight the selected chip. Pass `true` for create (always
   * active once a chip is clicked) or `expiryTouched` for edit (the edit
   * panel omits `expires_at` from the PATCH body unless the user explicitly
   * picks a chip, so no chip should appear selected until they do).
   */
  touched: boolean;
  /** Called with the chosen day-count when a chip is clicked. */
  onChange: (days: number | null) => void;
}

/**
 * Renders the expiry quick-pick chip row shared by APIKeyCreatePanel and
 * APIKeyEditPanel. Stateless — the parent owns `selectedDays` and `touched`.
 *
 * The `touched` flag exists because the edit panel intentionally shows no chip
 * as selected on first render (the key's existing expiry is left unchanged
 * unless the user explicitly picks a new value).
 *
 * Tier: features/access. Allowed deps: api/types (via apiKeyFormData), lib/.
 */
export function ExpiryChips({
  selectedDays,
  touched,
  onChange,
}: ExpiryChipsProps): React.ReactElement {
  return (
    <div className={styles['section']}>
      <span className={styles['section-label']}>Expiration</span>
      <div className={styles['chip-row']}>
        {EXPIRY_CHOICES.map((choice) => (
          <button
            key={choice.label}
            type="button"
            className={cn(
              styles['chip'],
              touched && selectedDays === choice.days && styles['chip-on'],
            )}
            aria-pressed={touched && selectedDays === choice.days}
            onClick={() => onChange(choice.days)}
          >
            {choice.label}
          </button>
        ))}
      </div>
    </div>
  );
}
