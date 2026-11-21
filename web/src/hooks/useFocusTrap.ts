import { useEffect, type RefObject } from 'react';

/** Matches every natively focusable interactive element. */
const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(', ');

/**
 * Focus management for a modal dialog: while `isOpen`, move focus into
 * `dialogRef`, keep Tab / Shift+Tab cycling inside it and call `onClose` on
 * Escape; restore the previously focused element on close.
 */
export function useFocusTrap(
  dialogRef: RefObject<HTMLElement | null>,
  isOpen: boolean,
  onClose: () => void,
): void {
  useEffect(() => {
    if (!isOpen) return undefined;

    const previouslyFocused = document.activeElement;

    // Next frame, so the dialog is in the DOM.
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

    return () => {
      cancelAnimationFrame(raf);
      if (previouslyFocused instanceof HTMLElement) {
        previouslyFocused.focus();
      }
    };
  }, [dialogRef, isOpen]);

  // Attached to the document, not the dialog's onKeyDown, so keystrokes are seen
  // even when the dialog itself holds focus right after opening.
  useEffect(() => {
    if (!isOpen) return undefined;

    function handleKeyDown(event: KeyboardEvent): void {
      if (event.key === 'Escape') {
        event.preventDefault();
        onClose();
        return;
      }

      if (event.key !== 'Tab') return;

      const dialog = dialogRef.current;
      if (!dialog) return;

      // No offsetParent visibility check: jsdom has no layout engine, so it
      // would treat every element as hidden.
      const focusable = Array.from(
        dialog.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
      );
      if (focusable.length === 0) return;

      const first = focusable[0];
      const last = focusable[focusable.length - 1];

      if (event.shiftKey) {
        if (document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        }
      } else {
        if (document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }
    }

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [dialogRef, isOpen, onClose]);
}
