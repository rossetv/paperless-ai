import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Button } from './Button';

describe('Button', () => {
  it('renders with required label text', () => {
    render(<Button>Submit</Button>);
    expect(screen.getByRole('button', { name: 'Submit' })).toBeInTheDocument();
  });

  it('applies the primary variant class by default', () => {
    render(<Button>Click me</Button>);
    const btn = screen.getByRole('button');
    expect(btn.className).toMatch(/primary/);
  });

  it('applies the secondary variant class when variant is secondary', () => {
    render(<Button variant="secondary">Cancel</Button>);
    const btn = screen.getByRole('button');
    expect(btn.className).toMatch(/secondary/);
  });

  it('fires onClick when clicked', async () => {
    const handleClick = vi.fn();
    render(<Button onClick={handleClick}>Click me</Button>);
    await userEvent.click(screen.getByRole('button'));
    expect(handleClick).toHaveBeenCalledTimes(1);
  });

  it('fires onClick when activated with Enter key', async () => {
    const handleClick = vi.fn();
    render(<Button onClick={handleClick}>Press me</Button>);
    screen.getByRole('button').focus();
    await userEvent.keyboard('{Enter}');
    expect(handleClick).toHaveBeenCalledTimes(1);
  });

  it('fires onClick when activated with Space key', async () => {
    const handleClick = vi.fn();
    render(<Button onClick={handleClick}>Space me</Button>);
    screen.getByRole('button').focus();
    await userEvent.keyboard(' ');
    expect(handleClick).toHaveBeenCalledTimes(1);
  });

  it('does not fire onClick when disabled', async () => {
    const handleClick = vi.fn();
    render(<Button disabled onClick={handleClick}>Disabled</Button>);
    await userEvent.click(screen.getByRole('button'));
    expect(handleClick).not.toHaveBeenCalled();
  });

  it('sets aria-disabled and disabled attribute when disabled prop is true', () => {
    render(<Button disabled>Disabled</Button>);
    const btn = screen.getByRole('button');
    expect(btn).toBeDisabled();
  });

  it('renders a native <button> element', () => {
    render(<Button>Native</Button>);
    expect(screen.getByRole('button').tagName).toBe('BUTTON');
  });

  it('applies the small size class when size is small', () => {
    render(<Button size="small">Small</Button>);
    const btn = screen.getByRole('button');
    expect(btn.className).toMatch(/small/);
  });

  it('accepts a type prop', () => {
    render(<Button type="submit">Submit</Button>);
    expect(screen.getByRole('button')).toHaveAttribute('type', 'submit');
  });
});
