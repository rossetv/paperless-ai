import { render, screen } from '@testing-library/react';
import { Spinner } from './Spinner';

describe('Spinner', () => {
  it('renders a status element', () => {
    render(<Spinner />);
    expect(screen.getByRole('status')).toBeInTheDocument();
  });

  it('has an accessible label by default', () => {
    render(<Spinner />);
    // Default label is "Loading…"
    expect(screen.getByRole('status')).toHaveAccessibleName('Loading…');
  });

  it('accepts a custom accessible label', () => {
    render(<Spinner label="Searching documents…" />);
    expect(screen.getByRole('status')).toHaveAccessibleName('Searching documents…');
  });

  it('applies the size-small class when size is "small"', () => {
    const { container } = render(<Spinner size="small" />);
    // CSS Modules hash class names; check className string contains 'small'
    expect((container.firstChild as Element).className).toMatch(/small/);
  });

  it('applies the size-medium class by default', () => {
    const { container } = render(<Spinner />);
    expect((container.firstChild as Element).className).toMatch(/medium/);
  });

  it('applies the size-large class when size is "large"', () => {
    const { container } = render(<Spinner size="large" />);
    expect((container.firstChild as Element).className).toMatch(/large/);
  });

  it('renders a visually hidden accessible label text', () => {
    render(<Spinner label="Fetching results" />);
    // The label text is in a visually-hidden span, still accessible
    expect(screen.getByText('Fetching results')).toBeInTheDocument();
  });

  it('forwards a custom className', () => {
    const { container } = render(<Spinner className="my-spinner" />);
    expect((container.firstChild as Element).className).toContain('my-spinner');
  });
});
