import React, { useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { Icon } from '../../primitives/Icon/Icon';
import { IconButton } from '../../primitives/IconButton/IconButton';
import { cn } from '../../../lib/cn';
import { useFocusTrap } from '../../../hooks/useFocusTrap';
import styles from './Modal.module.css';

let scrollLocks = 0;
let overflowBeforeLock = '';

/** Locks body scroll while any modal is open; the last one out restores it. */
function lockBodyScroll(): () => void {
  if (scrollLocks === 0) {
    overflowBeforeLock = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
  }
  scrollLocks += 1;
  return () => {
    scrollLocks -= 1;
    if (scrollLocks === 0) document.body.style.overflow = overflowBeforeLock;
  };
}

export interface ModalProps {
  /** Whether the modal is visible and mounted. */
  isOpen: boolean;
  /**
   * Accessible title — rendered in the modal header and linked via
   * aria-labelledby so screen readers announce it when the dialog opens.
   */
  title: string;
  /** Called when the user dismisses the modal (close button, Escape, backdrop). */
  onClose: () => void;
  children: React.ReactNode;
  className?: string;
}

/**
 * Accessible modal dialog, portalled into document.body so it sits above every
 * stacking context. Focus is trapped while open (via `useFocusTrap`) and restored
 * on close; Escape and backdrop clicks call `onClose`. Body scroll is locked while
 * open. Initial focus goes to the first focusable element of the content, or to
 * the element marked `data-autofocus`.
 */
export function Modal({
  isOpen,
  title,
  onClose,
  children,
  className,
}: ModalProps): React.ReactElement | null {
  const dialogRef = useRef<HTMLDialogElement>(null);

  const titleId = React.useId();

  useFocusTrap(dialogRef, isOpen, onClose);

  useEffect(() => (isOpen ? lockBodyScroll() : undefined), [isOpen]);

  if (!isOpen) return null;

  return createPortal(
    <div className={styles['overlay']}>
      <div
        className={styles['backdrop']}
        data-testid="modal-backdrop"
        aria-hidden="true"
        onClick={onClose}
      />

      <dialog
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className={cn(styles['panel'], className)}
        // tabIndex -1 lets the dialog itself receive programmatic focus when no
        // children are focusable, but keeps it out of the natural tab order.
        tabIndex={-1}
        open
      >
        <div className={styles['header']}>
          <h2 id={titleId} className={styles['title']}>
            {title}
          </h2>
          <IconButton
            label="Close modal"
            onClick={onClose}
            className={styles['close-button'] ?? ''}
          >
            <Icon name="close" size="small" />
          </IconButton>
        </div>

        <div className={styles['body']} data-focus-content="">{children}</div>
      </dialog>
    </div>,
    document.body,
  );
}
