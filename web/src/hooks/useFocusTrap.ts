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
 *
 * Initial focus goes to the element marked `data-autofocus`, else the first
 * focusable one inside `data-focus-content` if the dialog has one, else the first
 * focusable one, else the dialog itself. An Escape that a child already handled (`defaultPrevented`)
 * is ignored.
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
      // A child that took focus itself on mount (React's autoFocus) keeps it.
      if (dialog.contains(document.activeElement)) return;
      const content = dialog.querySelector<HTMLElement>('[data-focus-content]');
      const target =
        dialog.querySelector<HTMLElement>('[data-autofocus]') ??
        content?.querySelector<HTMLElement>(FOCUSABLE_SELECTOR) ??
        dialog.querySelector<HTMLElement>(FOCUSABLE_SELECTOR) ??
        dialog;
      target.focus();
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
        // React's handlers run at the root, below the document, so a child's
        // preventDefault has already happened by the time this runs.
        if (event.defaultPrevented) return;
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
