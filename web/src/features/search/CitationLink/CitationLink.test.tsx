import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { CitationLink } from './CitationLink';

describe('CitationLink', () => {
  it('renders the citation number', () => {
    render(<CitationLink index={2} onActivate={() => {}} />);
    expect(screen.getByText('2')).toBeInTheDocument();
  });

  it('exposes an accessible "Citation n" name', () => {
    render(<CitationLink index={3} onActivate={() => {}} />);
    expect(
      screen.getByRole('button', { name: /citation 3/i }),
    ).toBeInTheDocument();
  });

  it('calls onActivate with the index when clicked', async () => {
    const onActivate = vi.fn();
    render(<CitationLink index={4} onActivate={onActivate} />);
    await userEvent.click(screen.getByRole('button'));
    expect(onActivate).toHaveBeenCalledWith(4);
  });
});
