import { render, screen } from '@testing-library/react';
import { FullPageLoading } from './FullPageLoading';

describe('FullPageLoading', () => {
  it('renders with role="status" for assistive technology', () => {
    render(<FullPageLoading />);
    expect(screen.getByRole('status')).toBeInTheDocument();
  });

  it('renders the loading label text', () => {
    render(<FullPageLoading />);
    expect(screen.getByText('Loading…')).toBeInTheDocument();
  });

  it('renders a single root container', () => {
    const { container } = render(<FullPageLoading />);
    expect(container.firstChild).not.toBeNull();
    expect((container.firstChild as Element).tagName).toBe('DIV');
  });
});
