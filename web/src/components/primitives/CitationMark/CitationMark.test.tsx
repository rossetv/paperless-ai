import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { CitationMark } from './CitationMark';

describe('CitationMark', () => {
  it('renders the citation number', () => {
    render(<CitationMark index={3} onActivate={() => {}} />);
    expect(screen.getByText('3')).toBeInTheDocument();
  });

  it('is a real button', () => {
    render(<CitationMark index={1} onActivate={() => {}} />);
    expect(screen.getByRole('button')).toBeInTheDocument();
  });

  it('has an accessible name "View source N" by default', () => {
    render(<CitationMark index={2} onActivate={() => {}} />);
    expect(
      screen.getByRole('button', { name: /view source 2/i }),
    ).toBeInTheDocument();
  });

  it('enriches the accessible name with the source title when provided', () => {
    render(
      <CitationMark index={2} onActivate={() => {}} sourceTitle="AIB Bank Statement" />,
    );
    expect(
      screen.getByRole('button', { name: /view source 2: aib bank statement/i }),
    ).toBeInTheDocument();
  });

  it('calls onActivate with the index on click', async () => {
    const onActivate = vi.fn();
    render(<CitationMark index={4} onActivate={onActivate} />);
    await userEvent.click(screen.getByRole('button'));
    expect(onActivate).toHaveBeenCalledWith(4);
  });

  it('calls onActivate on keyboard activation', async () => {
    const onActivate = vi.fn();
    render(<CitationMark index={5} onActivate={onActivate} />);
    screen.getByRole('button').focus();
    await userEvent.keyboard('{Enter}');
    expect(onActivate).toHaveBeenCalledWith(5);
  });

  it('merges a custom className', () => {
    render(<CitationMark index={1} onActivate={() => {}} className="extra" />);
    expect(screen.getByRole('button').className).toContain('extra');
  });
});
