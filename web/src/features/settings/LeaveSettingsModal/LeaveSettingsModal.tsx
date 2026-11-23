import React from 'react';
import { Modal } from '../../../components/patterns/Modal/Modal';
import { Button } from '../../../components/primitives/Button/Button';
import styles from './LeaveSettingsModal.module.css';

export interface LeaveSettingsModalProps {
  /** Keep editing; also what Escape and the backdrop do. */
  onStay: () => void;
  /** Discard the unsaved edits and go on to the page that was asked for. */
  onLeave: () => void;
}

/** Asks before an in-app navigation drops unsaved settings. Always open: the parent mounts it. */
export function LeaveSettingsModal({ onStay, onLeave }: LeaveSettingsModalProps): React.ReactElement {
  const buttonsRef = React.useRef<HTMLDivElement>(null);
  // Button takes no autofocus marker, and the modal would focus its close button first.
  React.useEffect(() => {
    buttonsRef.current?.querySelector<HTMLElement>('button:last-of-type')?.focus();
  }, []);

  return (
    <Modal isOpen title="Leave without saving?" onClose={onStay}>
      <p className={styles['body']}>Your changes to settings will be lost.</p>
      <div ref={buttonsRef} className={styles['buttons']}>
        <Button variant="ghost" onClick={onLeave}>
          Leave
        </Button>
        <Button onClick={onStay}>Stay</Button>
      </div>
    </Modal>
  );
}
