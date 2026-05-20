import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { CitationLink } from './CitationLink';

describe('CitationLink', () => {
  it('renders the citation index as [n]', () => {
    render(<CitationLink index={3} onActivate={vi.fn()} />);
    expect(screen.getByRole('button', { name: /citation 3/i })).toBeInTheDocument();
    expect(screen.getByText('[3]')).toBeInTheDocument();
  });

  it('calls onActivate with the citation index when clicked', async () => {
    const handler = vi.fn();
    render(<CitationLink index={1} onActivate={handler} />);
    await userEvent.click(screen.getByRole('button'));
    expect(handler).toHaveBeenCalledOnce();
    expect(handler).toHaveBeenCalledWith(1);
  });

  it('calls onActivate when activated with Enter', async () => {
    const handler = vi.fn();
    render(<CitationLink index={2} onActivate={handler} />);
    screen.getByRole('button').focus();
    await userEvent.keyboard('{Enter}');
    expect(handler).toHaveBeenCalledWith(2);
  });

  it('calls onActivate when activated with Space', async () => {
    const handler = vi.fn();
    render(<CitationLink index={5} onActivate={handler} />);
    screen.getByRole('button').focus();
    await userEvent.keyboard(' ');
    expect(handler).toHaveBeenCalledWith(5);
  });

  it('renders as a <button> element (keyboard operable, not an anchor)', () => {
    render(<CitationLink index={1} onActivate={vi.fn()} />);
    expect(screen.getByRole('button').tagName).toBe('BUTTON');
  });
});
