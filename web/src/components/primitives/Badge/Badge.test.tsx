import { render, screen } from '@testing-library/react';
import { Badge } from './Badge';

// The label sits in an inner span so it can truncate; the badge is its parent.
const badgeOf = (text: string): HTMLElement => screen.getByText(text).parentElement as HTMLElement;

describe('Badge', () => {
  it('renders with its label text', () => {
    render(<Badge>New</Badge>);
    expect(screen.getByText('New')).toBeInTheDocument();
  });

  it('renders a <span> element by default', () => {
    render(<Badge>Status</Badge>);
    expect(badgeOf('Status').tagName).toBe('SPAN');
  });

  it('applies the neutral variant class by default', () => {
    render(<Badge>Default</Badge>);
    expect(badgeOf('Default').className).toMatch(/neutral/);
  });

  it('applies the accent variant class when variant is accent', () => {
    render(<Badge variant="accent">Accent</Badge>);
    expect(badgeOf('Accent').className).toMatch(/accent/);
  });

  it('forwards a custom className', () => {
    render(<Badge className="custom-cls">Label</Badge>);
    expect(badgeOf('Label').className).toContain('custom-cls');
  });

  it('renders numeric children', () => {
    render(<Badge>{42}</Badge>);
    expect(screen.getByText('42')).toBeInTheDocument();
  });

  it('shows its full text as a tooltip when given a title', () => {
    render(<Badge title="A very long correspondent name">A very long…</Badge>);
    expect(badgeOf('A very long…')).toHaveAttribute('title', 'A very long correspondent name');
  });
});
