import { render, screen, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import React, { useRef } from 'react';
import { ChunkPopover } from './ChunkPopover';

function PopoverHarness(): React.ReactElement {
  const containerRef = useRef<HTMLDivElement>(null);
  return (
    <div>
      <div ref={containerRef}>
        <span
          tabIndex={0}
          data-title="Land Registry Deed"
          data-score="0.74"
          data-full="The full chunk text about the land registry."
        >
          snippet preview
        </span>
      </div>
      <ChunkPopover containerRef={containerRef} />
    </div>
  );
}

describe('ChunkPopover', () => {
  it('is hidden by default', () => {
    render(<PopoverHarness />);
    const pop = document.querySelector('[role="tooltip"]');
    expect(pop).not.toBeNull();
    expect(pop!.getAttribute('data-visible')).toBe('false');
  });

  it('shows on focus and contains the title and full text', async () => {
    render(<PopoverHarness />);
    const snip = screen.getByText('snippet preview');
    await act(async () => {
      snip.focus();
    });
    const pop = document.querySelector('[role="tooltip"]');
    expect(pop!.getAttribute('data-visible')).toBe('true');
    expect(pop!.textContent).toContain('Land Registry Deed');
    expect(pop!.textContent).toContain('The full chunk text about the land registry.');
  });

  it('hides on blur', async () => {
    render(<PopoverHarness />);
    const snip = screen.getByText('snippet preview');
    await act(async () => {
      snip.focus();
    });
    await act(async () => {
      snip.blur();
      // wait for the 80ms hide timer
      await new Promise((r) => setTimeout(r, 120));
    });
    const pop = document.querySelector('[role="tooltip"]');
    expect(pop!.getAttribute('data-visible')).toBe('false');
  });

  it('hides on Escape keydown', async () => {
    render(<PopoverHarness />);
    const snip = screen.getByText('snippet preview');
    await act(async () => {
      snip.focus();
    });
    await userEvent.keyboard('{Escape}');
    await act(async () => {
      await new Promise((r) => setTimeout(r, 120));
    });
    const pop = document.querySelector('[role="tooltip"]');
    expect(pop!.getAttribute('data-visible')).toBe('false');
  });
});
