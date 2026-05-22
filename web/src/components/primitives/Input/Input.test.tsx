import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Input } from './Input';

describe('Input', () => {
  it('renders with a visible label when label prop is provided', () => {
    render(<Input id="name" label="Full name" />);
    expect(screen.getByLabelText('Full name')).toBeInTheDocument();
  });

  it('associates the label with the input via id', () => {
    render(<Input id="email" label="Email address" />);
    const input = screen.getByRole('textbox');
    expect(input).toHaveAttribute('id', 'email');
    expect(screen.getByText('Email address').tagName).toBe('LABEL');
  });

  it('renders a native <input> element', () => {
    render(<Input id="test" />);
    // getByRole('textbox') confirms it is an <input> or <textarea>; check tag
    expect(screen.getByRole('textbox').tagName).toBe('INPUT');
  });

  it('forwards value and onChange for controlled usage', async () => {
    const handleChange = vi.fn();
    render(<Input id="q" value="hello" onChange={handleChange} />);
    const input = screen.getByRole('textbox');
    expect(input).toHaveValue('hello');
    await userEvent.type(input, 'x');
    expect(handleChange).toHaveBeenCalled();
  });

  it('sets placeholder text', () => {
    render(<Input id="search" placeholder="Search documents…" />);
    expect(screen.getByPlaceholderText('Search documents…')).toBeInTheDocument();
  });

  it('is disabled when disabled prop is true', () => {
    render(<Input id="off" disabled />);
    expect(screen.getByRole('textbox')).toBeDisabled();
  });

  it('renders an error message when error prop is provided', () => {
    render(<Input id="bad" error="This field is required" />);
    expect(screen.getByText('This field is required')).toBeInTheDocument();
  });

  it('sets aria-invalid when error prop is provided', () => {
    render(<Input id="bad" error="Required" />);
    expect(screen.getByRole('textbox')).toHaveAttribute('aria-invalid', 'true');
  });

  it('does not set aria-invalid when no error prop', () => {
    render(<Input id="good" />);
    expect(screen.getByRole('textbox')).not.toHaveAttribute('aria-invalid', 'true');
  });

  it('accepts type prop (e.g. email)', () => {
    render(<Input id="mail" type="email" />);
    expect(screen.getByRole('textbox')).toHaveAttribute('type', 'email');
  });

  it('forwards the name attribute', () => {
    render(<Input id="f" name="query" />);
    expect(screen.getByRole('textbox')).toHaveAttribute('name', 'query');
  });

  it('applies the dark control class when surface="dark"', () => {
    render(<Input id="dk" label="Username" surface="dark" />);
    expect(screen.getByRole('textbox').className).toMatch(/input-dark/);
  });

  it('uses the light control by default (no dark class)', () => {
    render(<Input id="lt" label="Username" />);
    expect(screen.getByRole('textbox').className).not.toMatch(/input-dark/);
  });

  it('forwards surface="dark" through to the FormField label', () => {
    const { container } = render(<Input id="dl" label="Password" surface="dark" />);
    const label = container.querySelector('label');
    expect(label?.className).toMatch(/label-dark/);
  });
});
