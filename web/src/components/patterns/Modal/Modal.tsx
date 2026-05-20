import React, { useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { Icon } from '../../primitives/Icon/Icon';
import { IconButton } from '../../primitives/IconButton/IconButton';
import stylesRaw from './Modal.module.css';

// CSS Modules return a string-indexed object; bracket notation is required
// under noPropertyAccessFromIndexSignature (tsconfig strict mode).
const styles = stylesRaw as Record<string, string>;

/** Selector string that matches every natively focusable interactive element. */
const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(', ');

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
  // Ref to the dialog panel — used for focus-trap queries and focus() on open.
  const dialogRef = useRef<HTMLDialogElement>(null);

  // The element that held focus before the modal opened — restored on close.
  const previousFocusRef = useRef<Element | null>(null);

  // Stable title id for aria-labelledby.
  const titleId = React.useId();

  // ── Save & restore focus ─────────────────────────────────────────────────
  useEffect(() => {
    if (isOpen) {
      // Remember whatever had focus at the moment we open.
      previousFocusRef.current = document.activeElement;

      // Move focus into the modal on the next tick so the dialog is in the DOM.
      const raf = requestAnimationFrame(() => {
        const dialog = dialogRef.current;
        if (!dialog) return;
        const firstFocusable = dialog.querySelector<HTMLElement>(FOCUSABLE_SELECTOR);
        if (firstFocusable) {
          firstFocusable.focus();
        } else {
          dialog.focus();
        }
      });
      return () => cancelAnimationFrame(raf);
    } else {
      // Restore focus when the modal closes.
      const target = previousFocusRef.current;
      if (target instanceof HTMLElement) {
        target.focus();
      }
      previousFocusRef.current = null;
      return undefined;
    }
  }, [isOpen]);

  // ── Keyboard handling — Escape + focus trap ──────────────────────────────
  // We attach to the document rather than the dialog's onKeyDown so that
  // keyboard events reach us regardless of which element inside the modal
  // currently holds focus. This also captures Escape when the dialog itself
  // has focus (e.g. right after opening with no focusable children).
  useEffect(() => {
    if (!isOpen) return undefined;

    function handleKeyDown(event: KeyboardEvent): void {
      if (event.key === 'Escape') {
        event.preventDefault();
        onClose();
        return;
      }

      if (event.key === 'Tab') {
        const dialog = dialogRef.current;
        if (!dialog) return;

        // Query all focusable children. We intentionally omit the offsetParent
        // visibility check because jsdom has no layout engine; a tab-index
        // element present in the DOM is considered reachable.
        const focusable = Array.from(
          dialog.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
        );

        if (focusable.length === 0) return;

        const first = focusable[0];
        const last = focusable[focusable.length - 1];

        if (event.shiftKey) {
          // Shift+Tab: if focus is on the first element, wrap to last.
          if (document.activeElement === first) {
            event.preventDefault();
            last?.focus();
          }
        } else {
          // Tab: if focus is on the last element, wrap to first.
          if (document.activeElement === last) {
            event.preventDefault();
            first?.focus();
          }
        }
      }
    }

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const panelClasses = [styles['panel'], className].filter(Boolean).join(' ');

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
        className={panelClasses}
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
