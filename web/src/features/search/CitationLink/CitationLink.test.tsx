import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { CitationLink } from './CitationLink';

describe('CitationLink', () => {
  it('renders the citation number', () => {
    render(<CitationLink index={2} onActivate={() => {}} />);
    expect(screen.getByText('2')).toBeInTheDocument();
  });

  it('exposes an accessible "View source N" name', () => {
    render(<CitationLink index={3} onActivate={() => {}} />);
    expect(
      screen.getByRole('button', { name: /view source 3/i }),
    ).toBeInTheDocument();
  });

  it('enriches the accessible name with the source title when provided', () => {
    render(
      <CitationLink index={3} onActivate={() => {}} sourceTitle="AIB Bank Statement" />,
    );
    expect(
      screen.getByRole('button', { name: /view source 3: aib bank statement/i }),
    ).toBeInTheDocument();
  });

  it('calls onActivate with the index when clicked', async () => {
    const onActivate = vi.fn();
    render(<CitationLink index={4} onActivate={onActivate} />);
    await userEvent.click(screen.getByRole('button'));
    expect(onActivate).toHaveBeenCalledWith(4);
  });
});
