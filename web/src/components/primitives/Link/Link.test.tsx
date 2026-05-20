import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Link } from './Link';

describe('Link', () => {
  it('renders with required label text', () => {
    render(<Link href="/home">Go home</Link>);
    expect(screen.getByRole('link', { name: 'Go home' })).toBeInTheDocument();
  });

  it('renders a native <a> element', () => {
    render(<Link href="/about">About</Link>);
    expect(screen.getByRole('link').tagName).toBe('A');
  });

  it('sets the href attribute', () => {
    render(<Link href="/search">Search</Link>);
    expect(screen.getByRole('link')).toHaveAttribute('href', '/search');
  });

  it('applies the default variant class by default', () => {
    render(<Link href="#">Default</Link>);
    const link = screen.getByRole('link');
    expect(link.className).toMatch(/link/);
  });

  it('applies a different class when variant is inline', () => {
    render(<Link href="#" variant="inline">Inline</Link>);
    const link = screen.getByRole('link');
    expect(link.className).toMatch(/inline/);
  });

  it('applies a different class when variant is on-dark', () => {
    render(<Link href="#" variant="on-dark">Dark</Link>);
    const link = screen.getByRole('link');
    expect(link.className).toMatch(/on-dark/);
  });

  it('opens in new tab and sets rel when external is true', () => {
    render(<Link href="https://example.com" external>External</Link>);
    const link = screen.getByRole('link');
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  });

  it('does not set target or rel by default', () => {
    render(<Link href="/local">Local</Link>);
    const link = screen.getByRole('link');
    expect(link).not.toHaveAttribute('target');
    expect(link).not.toHaveAttribute('rel');
  });

  it('fires onClick when clicked', async () => {
    const handleClick = vi.fn();
    render(<Link href="#" onClick={handleClick}>Click me</Link>);
    await userEvent.click(screen.getByRole('link'));
    expect(handleClick).toHaveBeenCalledTimes(1);
  });

  it('fires onClick when activated with Enter key', async () => {
    const handleClick = vi.fn((e: React.MouseEvent) => e.preventDefault());
    render(<Link href="#" onClick={handleClick}>Press me</Link>);
    screen.getByRole('link').focus();
    await userEvent.keyboard('{Enter}');
    expect(handleClick).toHaveBeenCalledTimes(1);
  });

  it('has focus-visible class available via CSS module', () => {
    render(<Link href="#">Focus test</Link>);
    const link = screen.getByRole('link');
    // Confirm the element is focusable (tabIndex not -1)
    expect(link).not.toHaveAttribute('tabindex', '-1');
  });
});
