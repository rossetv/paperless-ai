import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ConnectionCard } from './ConnectionCard';

function makeCard(overrides: Partial<React.ComponentProps<typeof ConnectionCard>> = {}) {
  return (
    <ConnectionCard
      glyph="P"
      glyphTone="blue"
      title="Paperless-ngx"
      subtitle="Where documents live"
      status={{ tone: 'untested', label: 'Untested' }}
      onTest={() => undefined}
      {...overrides}
    >
      <div data-testid="card-body">body content</div>
    </ConnectionCard>
  );
}

/** The accordion header toggle button — matches exact name "Paperless-ngx". */
function getHeaderToggle() {
  return screen.getByRole('button', { name: 'Paperless-ngx' });
}

describe('ConnectionCard', () => {
  it('starts collapsed — body not visible', () => {
    render(makeCard());
    expect(screen.queryByTestId('card-body')).not.toBeVisible();
  });

  it('expands on header click and body becomes visible', async () => {
    render(makeCard());
    await userEvent.click(getHeaderToggle());
    expect(screen.getByTestId('card-body')).toBeVisible();
  });

  it('collapses again on second header click', async () => {
    render(makeCard());
    await userEvent.click(getHeaderToggle());
    await userEvent.click(getHeaderToggle());
    expect(screen.queryByTestId('card-body')).not.toBeVisible();
  });

  it('can start expanded when defaultOpen is true', () => {
    render(makeCard({ defaultOpen: true }));
    expect(screen.getByTestId('card-body')).toBeVisible();
  });

  it('clicking Test fires onTest WITHOUT expanding the card', async () => {
    const onTest = vi.fn();
    render(makeCard({ onTest }));
    await userEvent.click(screen.getByRole('button', { name: /^Test Paperless-ngx$/i }));
    expect(onTest).toHaveBeenCalledTimes(1);
    // Body should still be hidden — test click must not toggle card
    expect(screen.queryByTestId('card-body')).not.toBeVisible();
  });

  it('clicking Test does not collapse an already-open card', async () => {
    const onTest = vi.fn();
    render(makeCard({ onTest, defaultOpen: true }));
    await userEvent.click(screen.getByRole('button', { name: /^Test Paperless-ngx$/i }));
    expect(onTest).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId('card-body')).toBeVisible();
  });

  it('status pill shows the label', () => {
    render(makeCard({ status: { tone: 'ok', label: 'Connected' } }));
    expect(screen.getByText('Connected')).toBeInTheDocument();
  });

  it('renders the glyph text', () => {
    render(makeCard({ glyph: 'AI', glyphTone: 'teal' }));
    expect(screen.getByText('AI')).toBeInTheDocument();
  });

  it('renders the three glyph tones without error', () => {
    const { rerender } = render(makeCard({ glyphTone: 'blue' }));
    rerender(makeCard({ glyphTone: 'teal' }));
    rerender(makeCard({ glyphTone: 'grey' }));
    // No throw = pass
  });

  it('header is keyboard-activatable with Enter', async () => {
    render(makeCard());
    const header = getHeaderToggle();
    header.focus();
    await userEvent.keyboard('{Enter}');
    expect(screen.getByTestId('card-body')).toBeVisible();
  });

  it('header is keyboard-activatable with Space', async () => {
    render(makeCard());
    const header = getHeaderToggle();
    header.focus();
    await userEvent.keyboard(' ');
    expect(screen.getByTestId('card-body')).toBeVisible();
  });
});
