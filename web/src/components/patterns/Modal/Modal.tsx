import React, { useRef } from 'react';
import { createPortal } from 'react-dom';
import { Icon } from '../../primitives/Icon/Icon';
import { IconButton } from '../../primitives/IconButton/IconButton';
import { cn } from '../../../lib/cn';
import { useFocusTrap } from '../../../hooks/useFocusTrap';
import styles from './Modal.module.css';

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
  /** Content rendered inside the modal panel. */
  children: React.ReactNode;
  /** Additional class names to merge onto the dialog panel. */
  className?: string;
}

/**
 * Accessible overlay modal dialog.
 *
 * Accessibility contract:
 * - role="dialog" + aria-modal="true" on the panel element.
 * - aria-labelledby points to the rendered title.
 * - Focus is trapped inside the modal while it is open: Tab and Shift+Tab cycle
 *   within the focusable children; nothing outside receives focus.
 * - Escape key fires onClose.
 * - Clicking the backdrop fires onClose.
 * - Focus is saved on open and restored to the previously-focused element on close.
 *
 * The focus management (move-in, trap, restore, Escape) lives in the generic
 * `useFocusTrap` hook so Modal stays a thin, presentational component.
 *
 * Rendered via createPortal into document.body so the dialog sits above all
 * page stacking contexts regardless of where in the tree Modal is used.
 *
 * App-agnostic — carries no knowledge of documents, search, or facets.
 */
export function Modal({
  isOpen,
  title,
  onClose,
  children,
  className,
}: ModalProps): React.ReactElement | null {
  // Ref to the dialog panel — used by the focus trap for queries and focus().
  const dialogRef = useRef<HTMLDialogElement>(null);

  // Stable title id for aria-labelledby.
  const titleId = React.useId();

  useFocusTrap(dialogRef, isOpen, onClose);

  if (!isOpen) return null;

  return createPortal(
    <div className={styles['overlay']}>
      {/* Backdrop — clicking it dismisses the modal */}
      <div
        className={styles['backdrop']}
        data-testid="modal-backdrop"
        aria-hidden="true"
        onClick={onClose}
      />

      {/* Dialog panel */}
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
        {/* Header */}
        <div className={styles['header']}>
          <h2 id={titleId} className={styles['title']}>
            {title}
          </h2>
          <IconButton
            label="Close modal"
            onClick={onClose}
            {...(styles['close-button'] !== undefined
              ? { className: styles['close-button'] }
              : {})}
          >
            <Icon name="close" size="small" />
          </IconButton>
        </div>

        {/* Body */}
        <div className={styles['body']}>{children}</div>
      </dialog>
    </div>,
    document.body,
  );
}
