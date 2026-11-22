import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import React from 'react';
import { MemoryRouter, useNavigate } from 'react-router-dom';
import { useRouteAnnounce } from './useRouteAnnounce';

let setHeading: (h: string | null) => void;
let go: (to: string) => void;

function Harness(): React.ReactElement {
  const wrapper = React.useRef<HTMLDivElement>(null);
  const [heading, set] = React.useState<string | null>(null);
  const navigate = useNavigate();
  setHeading = set;
  go = navigate;
  useRouteAnnounce(wrapper);
  return (
    <div ref={wrapper} tabIndex={-1} data-testid="wrapper">
      {/* a changing key replaces the element, like a loading branch swapping layouts */}
      {heading !== null && <h1 key={heading}>{heading}</h1>}
      <button type="button">other</button>
    </div>
  );
}

function renderAt(): void {
  render(
    <MemoryRouter initialEntries={['/library']}>
      <Harness />
    </MemoryRouter>,
  );
}

const flush = (): Promise<void> => act(async () => {});

describe('useRouteAnnounce late headings', () => {
  it('focuses a heading that renders after the navigation commits', async () => {
    renderAt();
    act(() => go('/index'));
    expect(screen.getByTestId('wrapper')).toHaveFocus();
    act(() => setHeading('Index'));
    await flush();
    expect(screen.getByRole('heading', { name: 'Index' })).toHaveFocus();
  });

  it('refocuses a heading that is replaced after it took focus', async () => {
    renderAt();
    act(() => setHeading('Loading'));
    act(() => go('/index'));
    expect(screen.getByRole('heading', { name: 'Loading' })).toHaveFocus();
    act(() => setHeading('Index'));
    await flush();
    expect(screen.getByRole('heading', { name: 'Index' })).toHaveFocus();
  });

  it('does not outline the heading it focuses', () => {
    renderAt();
    act(() => setHeading('Index'));
    act(() => go('/index'));
    expect(screen.getByRole('heading', { name: 'Index' })).toHaveStyle({ outline: 'none' });
  });

  it('restores the heading outline once it blurs', () => {
    renderAt();
    act(() => setHeading('Index'));
    act(() => go('/index'));
    const h1 = screen.getByRole('heading', { name: 'Index' });
    expect(h1.style.outline).toBe('none');
    act(() => screen.getByRole('button', { name: 'other' }).focus());
    expect(h1.style.outline).toBe('');
  });

  it('stops waiting once a key is pressed', async () => {
    renderAt();
    act(() => go('/index'));
    await userEvent.keyboard('a');
    act(() => setHeading('Index'));
    await flush();
    expect(screen.getByRole('heading', { name: 'Index' })).not.toHaveFocus();
  });

  it('does not steal focus the user moved elsewhere', async () => {
    renderAt();
    act(() => go('/index'));
    act(() => screen.getByRole('button', { name: 'other' }).focus());
    act(() => setHeading('Index'));
    await flush();
    expect(screen.getByRole('button', { name: 'other' })).toHaveFocus();
  });

  it('stops observing on unmount and on the next navigation', () => {
    const disconnect = vi.spyOn(MutationObserver.prototype, 'disconnect');
    renderAt();
    act(() => go('/index'));
    act(() => go('/settings'));
    expect(disconnect).toHaveBeenCalledTimes(1);
    disconnect.mockClear();
    cleanup();
    expect(disconnect).toHaveBeenCalledTimes(1);
    disconnect.mockRestore();
  });

  describe('watch window', () => {
    beforeEach(() => vi.useFakeTimers());
    afterEach(() => vi.useRealTimers());

    it('still focuses a heading that appears after a slow load', async () => {
      renderAt();
      act(() => go('/settings'));
      await act(async () => { vi.advanceTimersByTime(3000); });
      act(() => setHeading('Settings'));
      await flush();
      expect(screen.getByRole('heading', { name: 'Settings' })).toHaveFocus();
    });

    it('stops waiting once a pointer is pressed', async () => {
      renderAt();
      act(() => go('/index'));
      fireEvent.pointerDown(document.body);
      act(() => setHeading('Index'));
      await flush();
      expect(screen.getByRole('heading', { name: 'Index' })).not.toHaveFocus();
    });

    it('stops waiting when the time runs out', async () => {
      renderAt();
      act(() => go('/index'));
      await act(async () => { vi.advanceTimersByTime(10_001); });
      act(() => setHeading('Index'));
      await flush();
      expect(screen.getByRole('heading', { name: 'Index' })).not.toHaveFocus();
    });
  });
});
