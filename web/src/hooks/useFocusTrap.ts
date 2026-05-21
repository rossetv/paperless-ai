/**
 * Focus management for a modal dialog.
 *
 * `useFocusTrap` owns the three behaviours an accessible overlay needs while
 * it is open:
 *   - move focus into the dialog when it opens, and restore it to the
 *     previously-focused element when it closes;
 *   - trap Tab / Shift+Tab so focus cycles within the dialog's focusable
 *     children and never escapes to the page behind it;
 *   - fire `onClose` on Escape.
 *
 * It is generic — it knows nothing about a specific dialog's content — so any
 * overlay component (Modal today, a Drawer or Popover tomorrow) can reuse it.
 *
 * Allowed deps: react only (leaf module — CODE_GUIDELINES §12.3, hooks allow []).
 */

import { useEffect, type RefObject } from 'react';

/** Selector string that matches every natively focusable interactive element. */
const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(', ');

/**
 * Trap focus inside `dialogRef` while `isOpen`, and call `onClose` on Escape.
 *
 * @param dialogRef - ref to the dialog element whose children focus is kept within.
 * @param isOpen    - whether the dialog is currently open.
 * @param onClose   - called when the user presses Escape.
 */
export function useFocusTrap(
  dialogRef: RefObject<HTMLElement | null>,
  isOpen: boolean,
  onClose: () => void,
): void {
  // ── Save & restore focus ───────────────────────────────────────────────
  useEffect(() => {
    if (!isOpen) return undefined;

    // Remember whatever had focus at the moment we open.
    const previouslyFocused = document.activeElement;

    // Move focus into the dialog on the next frame so it is in the DOM.
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
      // Restore focus to whatever held it before the dialog opened.
      if (previouslyFocused instanceof HTMLElement) {
        previouslyFocused.focus();
      }
    };
  }, [dialogRef, isOpen]);

  // ── Keyboard handling — Escape + Tab focus trap ────────────────────────
  // Attached to the document (not the dialog's onKeyDown) so keystrokes reach
  // us regardless of which element inside the dialog holds focus — including
  // the dialog itself, right after opening with no focusable children.
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

      // Query all focusable children. The offsetParent visibility check is
      // intentionally omitted — jsdom has no layout engine, so a tab-index
      // element present in the DOM is considered reachable.
      const focusable = Array.from(
        dialog.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
      );
      if (focusable.length === 0) return;

      const first = focusable[0];
      const last = focusable[focusable.length - 1];

      if (event.shiftKey) {
        // Shift+Tab on the first element wraps to the last.
        if (document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        }
      } else {
        // Tab on the last element wraps to the first.
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
