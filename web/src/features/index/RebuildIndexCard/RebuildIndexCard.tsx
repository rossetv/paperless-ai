import React from 'react';
import { cn } from '../../../lib/cn';
import { Modal } from '../../../components/patterns/Modal/Modal';
import { Button } from '../../../components/primitives/Button/Button';
import { Input } from '../../../components/primitives/Input/Input';
import { Icon } from '../../../components/primitives/Icon/Icon';
import { useRebuildIndex } from '../../../api/hooks';
import styles from './RebuildIndexCard.module.css';

/** The word the operator must type to arm the destructive rebuild. */
const CONFIRM_WORD = 'REBUILD';

export interface RebuildIndexCardProps {
  /** Additional class names to merge onto the root card. */
  className?: string;
}

/**
 * The Index dashboard "danger zone" — rebuild the index from scratch.
 *
 * A warning card whose button opens a confirmation `Modal`. The destructive
 * `POST /api/index/rebuild` only fires once the operator types the exact
 * word `REBUILD` into the confirmation field — a deliberate friction step
 * for an action that deletes `index.db` and costs hours plus API spend.
 *
 * Owns the `useRebuildIndex` mutation. `IndexScreen` renders this only for
 * an admin; the component itself carries no role check.
 *
 * Tier: features/index (CODE_GUIDELINES §12.3) — composes the Modal pattern,
 * the Button + Input primitives, and the rebuild mutation hook.
 */
export function RebuildIndexCard({
  className,
}: RebuildIndexCardProps): React.ReactElement {
  const [isModalOpen, setModalOpen] = React.useState(false);
  const [confirmText, setConfirmText] = React.useState('');
  const rebuild = useRebuildIndex();

  const confirmInputId = React.useId();
  const armed = confirmText === CONFIRM_WORD;

  function closeModal(): void {
    setModalOpen(false);
    setConfirmText('');
  }

  async function handleConfirm(): Promise<void> {
    if (!armed || rebuild.isPending) {
      return;
    }
    try {
      await rebuild.mutateAsync();
      closeModal();
    } catch {
      // The mutation's error state drives the in-modal error message; the
      // modal stays open so the operator can retry or cancel.
    }
  }

  return (
    <section className={cn(styles['card'], className)}>
      <span className={styles['icon']}>
        <Icon name="warning" size="small" />
      </span>
      <div>
        <h3 className={styles['title']}>Rebuild index from scratch</h3>
        <p className={styles['body']}>
          Deletes <code className={styles['code']}>index.db</code> and
          re-embeds every document. Takes roughly three hours for 14k
          documents and costs embedding API calls. The search server returns
          503 until the first reconcile finishes.
        </p>
      </div>
      <Button variant="secondary" onClick={() => setModalOpen(true)}>
        Rebuild index…
      </Button>

      <Modal
        isOpen={isModalOpen}
        title="Rebuild the search index?"
        onClose={closeModal}
      >
        <div className={styles['modal-body']}>
          <p className={styles['modal-text']}>
            This permanently deletes the current index and re-embeds every
            document from Paperless. It cannot be undone, and search is
            unavailable until the first reconcile completes.
          </p>
          <Input
            id={confirmInputId}
            label={`Type ${CONFIRM_WORD} to confirm`}
            value={confirmText}
            placeholder={CONFIRM_WORD}
            onChange={(e) => setConfirmText(e.target.value)}
          />
          {rebuild.isError && (
            <p className={styles['error']} role="alert">
              Could not start the rebuild. Check the server logs and try
              again.
            </p>
          )}
          <div className={styles['modal-actions']}>
            <Button variant="secondary" onClick={closeModal}>
              Cancel
            </Button>
            <Button
              variant="primary"
              disabled={!armed || rebuild.isPending}
              onClick={() => {
                void handleConfirm();
              }}
            >
              {rebuild.isPending ? 'Rebuilding…' : 'Rebuild now'}
            </Button>
          </div>
        </div>
      </Modal>
    </section>
  );
}
