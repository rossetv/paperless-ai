import { render, screen } from '@testing-library/react';
import { Badge } from './Badge';

describe('Badge', () => {
  it('renders with its label text', () => {
    render(<Badge>New</Badge>);
    expect(screen.getByText('New')).toBeInTheDocument();
  });

  it('renders a <span> element by default', () => {
    render(<Badge>Status</Badge>);
    expect(screen.getByText('Status').tagName).toBe('SPAN');
  });

  it('applies the neutral variant class by default', () => {
    render(<Badge>Default</Badge>);
    expect(screen.getByText('Default').className).toMatch(/neutral/);
  });

  it('applies the accent variant class when variant is accent', () => {
    render(<Badge variant="accent">Accent</Badge>);
    expect(screen.getByText('Accent').className).toMatch(/accent/);
  });

  it('applies the success variant class when variant is success', () => {
    render(<Badge variant="success">Done</Badge>);
    expect(screen.getByText('Done').className).toMatch(/success/);
  });

  it('applies the warning variant class when variant is warning', () => {
    render(<Badge variant="warning">Warn</Badge>);
    expect(screen.getByText('Warn').className).toMatch(/warning/);
  });

  it('applies the danger variant class when variant is danger', () => {
    render(<Badge variant="danger">Error</Badge>);
    expect(screen.getByText('Error').className).toMatch(/danger/);
  });

  it('forwards a custom className', () => {
    render(<Badge className="custom-cls">Label</Badge>);
    expect(screen.getByText('Label').className).toContain('custom-cls');
  });

  it('renders numeric children', () => {
    render(<Badge>{42}</Badge>);
    expect(screen.getByText('42')).toBeInTheDocument();
  });
});
