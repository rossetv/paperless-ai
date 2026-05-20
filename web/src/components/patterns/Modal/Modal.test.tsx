import React from 'react';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Modal } from './Modal';

// jsdom does not implement HTMLDialogElement.showModal/close natively,
// so we provide minimal stubs so Modal's imperativeAPI calls do not throw.
beforeEach(() => {
  if (!HTMLDialogElement.prototype.showModal) {
    HTMLDialogElement.prototype.showModal = function () {
      this.setAttribute('open', '');
    };
  }
  if (!HTMLDialogElement.prototype.close) {
    HTMLDialogElement.prototype.close = function () {
      this.removeAttribute('open');
    };
  }
});

describe('Modal', () => {
  it('renders nothing when isOpen is false', () => {
    render(
      <Modal isOpen={false} title="Test modal" onClose={vi.fn()}>
        <p>Modal body</p>
      </Modal>,
    );
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('renders the dialog with the correct title when isOpen is true', () => {
    render(
      <Modal isOpen title="Confirm action" onClose={vi.fn()}>
        <p>Are you sure?</p>
      </Modal>,
    );
    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByText('Confirm action')).toBeInTheDocument();
  });

  it('renders children inside the dialog', () => {
    render(
      <Modal isOpen title="Details" onClose={vi.fn()}>
        <p>Modal content here</p>
      </Modal>,
    );
    expect(screen.getByText('Modal content here')).toBeInTheDocument();
  });

  it('carries aria-modal="true" on the dialog element', () => {
    render(
      <Modal isOpen title="Accessible modal" onClose={vi.fn()}>
        <p>Body</p>
      </Modal>,
    );
    expect(screen.getByRole('dialog')).toHaveAttribute('aria-modal', 'true');
  });

  it('calls onClose when the close button is clicked', async () => {
    const handleClose = vi.fn();
    render(
      <Modal isOpen title="Close me" onClose={handleClose}>
        <p>Content</p>
      </Modal>,
    );
    await userEvent.click(screen.getByRole('button', { name: /close/i }));
    expect(handleClose).toHaveBeenCalledTimes(1);
  });

  it('calls onClose when Escape is pressed', async () => {
    const handleClose = vi.fn();
    render(
      <Modal isOpen title="Escape test" onClose={handleClose}>
        <p>Press escape</p>
      </Modal>,
    );
    await userEvent.keyboard('{Escape}');
    expect(handleClose).toHaveBeenCalledTimes(1);
  });

  it('calls onClose when the backdrop is clicked', async () => {
    const handleClose = vi.fn();
    render(
      <Modal isOpen title="Backdrop test" onClose={handleClose}>
        <p>Click outside</p>
      </Modal>,
    );
    // Modal renders via createPortal into document.body, so we query there.
    const backdrop = document.querySelector('[data-testid="modal-backdrop"]');
    expect(backdrop).toBeInTheDocument();
    await userEvent.click(backdrop as HTMLElement);
    expect(handleClose).toHaveBeenCalledTimes(1);
  });

  it('traps focus within the modal while it is open', async () => {
    render(
      <Modal isOpen title="Focus trap" onClose={vi.fn()}>
        <button type="button">First</button>
        <button type="button">Second</button>
      </Modal>,
    );
    // The dialog contains: [close button, First, Second].
    // Manually focus the last focusable element (Second) and fire a Tab
    // keydown — our document listener wraps focus to the first element.
    const second = screen.getByRole('button', { name: 'Second' });
    second.focus();
    expect(document.activeElement).toBe(second);

    // Simulate Tab keydown. userEvent.keyboard fires on the active element
    // and the event bubbles to document; our listener intercepts it.
    await userEvent.keyboard('{Tab}');

    // Focus should have been wrapped to the first focusable element in the
    // dialog (the close button), not escaped to somewhere outside.
    expect(screen.getByRole('dialog')).toContainElement(document.activeElement as HTMLElement);
    // Specifically: the close button should now be active.
    expect(document.activeElement).toBe(screen.getByRole('button', { name: /close/i }));
  });

  it('restores focus to the previously focused element when closed', async () => {
    const handleClose = vi.fn();

    function Harness(): React.ReactElement {
      const [open, setOpen] = React.useState(false);
      return (
        <>
          <button type="button" id="trigger" onClick={() => setOpen(true)}>
            Open
          </button>
          <Modal
            isOpen={open}
            title="Restore focus"
            onClose={() => {
              setOpen(false);
              handleClose();
            }}
          >
            <p>Content</p>
          </Modal>
        </>
      );
    }

    render(<Harness />);
    const trigger = screen.getByRole('button', { name: 'Open' });
    trigger.focus();
    await userEvent.click(trigger);

    // Modal is open — close it via Escape
    await userEvent.keyboard('{Escape}');

    // Focus must be restored to the trigger button
    expect(document.activeElement).toBe(trigger);
  });
});
