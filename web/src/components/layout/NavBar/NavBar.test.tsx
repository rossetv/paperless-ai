import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { NavBar } from './NavBar';

describe('NavBar', () => {
  it('renders its brand slot', () => {
    render(<NavBar brand={<span>My App</span>} />);
    expect(screen.getByText('My App')).toBeInTheDocument();
  });

  it('renders its actions slot when provided', () => {
    render(
      <NavBar
        brand={<span>Brand</span>}
        actions={<button type="button">Sign in</button>}
      />,
    );
    expect(screen.getByRole('button', { name: 'Sign in' })).toBeInTheDocument();
  });

  it('renders a <nav> element', () => {
    const { container } = render(<NavBar brand={<span>Brand</span>} />);
    expect(container.querySelector('nav')).toBeInTheDocument();
  });

  it('applies the base navbar class', () => {
    const { container } = render(<NavBar brand={<span>Brand</span>} />);
    const nav = container.querySelector('nav');
    expect(nav?.className).toMatch(/navbar/);
  });

  it('has an aria-label on the nav element', () => {
    const { container } = render(<NavBar brand={<span>Brand</span>} />);
    const nav = container.querySelector('nav');
    expect(nav).toHaveAttribute('aria-label');
  });

  it('forwards a custom aria-label', () => {
    const { container } = render(
      <NavBar brand={<span>Brand</span>} aria-label="Main navigation" />,
    );
    const nav = container.querySelector('nav');
    expect(nav).toHaveAttribute('aria-label', 'Main navigation');
  });

  it('forwards a custom className', () => {
    const { container } = render(<NavBar brand={<span>Brand</span>} className="custom" />);
    const nav = container.querySelector('nav');
    expect(nav?.className).toContain('custom');
  });

  it('renders the brand and actions in a single toolbar row', () => {
    render(
      <NavBar
        brand={<span>Brand</span>}
        actions={<span>Actions</span>}
      />,
    );
    expect(screen.getByText('Brand')).toBeInTheDocument();
    expect(screen.getByText('Actions')).toBeInTheDocument();
  });

  it('is keyboard-navigable: links inside are reachable with Tab', async () => {
    render(
      <NavBar
        brand={<a href="/">Home</a>}
        actions={<a href="/search">Search</a>}
      />,
    );
    const homeLink = screen.getByRole('link', { name: 'Home' });
    const searchLink = screen.getByRole('link', { name: 'Search' });

    homeLink.focus();
    expect(document.activeElement).toBe(homeLink);

    await userEvent.tab();
    expect(document.activeElement).toBe(searchLink);
  });
});
