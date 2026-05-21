/**
 * Tests for the useFocusTrap hook.
 *
 * Verifies the three behaviours of a modal focus trap: focus moves into the
 * dialog on open, Tab / Shift+Tab cycle within it, and Escape calls onClose.
 */

import React, { useRef } from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useFocusTrap } from './useFocusTrap';

/** A minimal dialog harness that wires the hook to a real DOM subtree. */
function TrapHarness({
  isOpen,
  onClose,
}: {
  isOpen: boolean;
  onClose: () => void;
}): React.ReactElement {
  const dialogRef = useRef<HTMLDivElement>(null);
  useFocusTrap(dialogRef, isOpen, onClose);
  return (
    <>
      <button type="button">outside before</button>
      {isOpen && (
        <div ref={dialogRef} role="dialog" tabIndex={-1}>
          <button type="button">first</button>
          <button type="button">last</button>
        </div>
      )}
      <button type="button">outside after</button>
    </>
  );
}

describe('useFocusTrap', () => {
  it('moves focus into the dialog when it opens', async () => {
    render(<TrapHarness isOpen onClose={vi.fn()} />);
    await waitFor(() => {
      expect(document.activeElement).toBe(
        screen.getByRole('button', { name: 'first' }),
      );
    });
  });

  it('calls onClose when Escape is pressed', async () => {
    const onClose = vi.fn();
    render(<TrapHarness isOpen onClose={onClose} />);
    await userEvent.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('wraps focus to the first element when Tab is pressed on the last', async () => {
    render(<TrapHarness isOpen onClose={vi.fn()} />);
    const last = screen.getByRole('button', { name: 'last' });
    last.focus();
    await userEvent.keyboard('{Tab}');
    expect(document.activeElement).toBe(
      screen.getByRole('button', { name: 'first' }),
    );
  });

  it('wraps focus to the last element when Shift+Tab is pressed on the first', async () => {
    render(<TrapHarness isOpen onClose={vi.fn()} />);
    const first = screen.getByRole('button', { name: 'first' });
    first.focus();
    await userEvent.keyboard('{Shift>}{Tab}{/Shift}');
    expect(document.activeElement).toBe(
      screen.getByRole('button', { name: 'last' }),
    );
  });

  it('does not call onClose on Escape while closed', async () => {
    const onClose = vi.fn();
    render(<TrapHarness isOpen={false} onClose={onClose} />);
    await userEvent.keyboard('{Escape}');
    expect(onClose).not.toHaveBeenCalled();
  });

  it('restores focus to the previously focused element when the dialog closes', async () => {
    function Harness(): React.ReactElement {
      const [open, setOpen] = React.useState(false);
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>
            open
          </button>
          <TrapHarness isOpen={open} onClose={() => setOpen(false)} />
        </>
      );
    }
    render(<Harness />);
    const trigger = screen.getByRole('button', { name: 'open' });
    trigger.focus();
    await userEvent.click(trigger);
    // Close via Escape — focus must return to the trigger.
    await userEvent.keyboard('{Escape}');
    await waitFor(() => {
      expect(document.activeElement).toBe(trigger);
    });
  });
});
