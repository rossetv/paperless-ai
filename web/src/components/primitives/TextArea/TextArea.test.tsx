import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { TextArea } from './TextArea';

describe('TextArea', () => {
  it('renders with a visible label when label prop is provided', () => {
    render(<TextArea id="notes" label="Notes" />);
    expect(screen.getByLabelText('Notes')).toBeInTheDocument();
  });

  it('associates the label with the textarea via id', () => {
    render(<TextArea id="message" label="Your message" />);
    const textarea = screen.getByRole('textbox');
    expect(textarea).toHaveAttribute('id', 'message');
    expect(screen.getByText('Your message').tagName).toBe('LABEL');
  });

  it('renders a native <textarea> element', () => {
    render(<TextArea id="t" />);
    expect(screen.getByRole('textbox').tagName).toBe('TEXTAREA');
  });

  it('forwards value and onChange for controlled usage', async () => {
    const handleChange = vi.fn();
    render(<TextArea id="q" value="initial" onChange={handleChange} />);
    const textarea = screen.getByRole('textbox');
    expect(textarea).toHaveValue('initial');
    await userEvent.type(textarea, 'x');
    expect(handleChange).toHaveBeenCalled();
  });

  it('sets placeholder text', () => {
    render(<TextArea id="n" placeholder="Describe your query…" />);
    expect(screen.getByPlaceholderText('Describe your query…')).toBeInTheDocument();
  });

  it('is disabled when disabled prop is true', () => {
    render(<TextArea id="off" disabled />);
    expect(screen.getByRole('textbox')).toBeDisabled();
  });

  it('renders an error message when error prop is provided', () => {
    render(<TextArea id="bad" error="This field cannot be blank" />);
    expect(screen.getByText('This field cannot be blank')).toBeInTheDocument();
  });

  it('sets aria-invalid when error prop is provided', () => {
    render(<TextArea id="bad" error="Required" />);
    expect(screen.getByRole('textbox')).toHaveAttribute('aria-invalid', 'true');
  });

  it('does not set aria-invalid when no error prop', () => {
    render(<TextArea id="good" />);
    expect(screen.getByRole('textbox')).not.toHaveAttribute('aria-invalid', 'true');
  });

  it('forwards the rows attribute', () => {
    render(<TextArea id="r" rows={6} />);
    expect(screen.getByRole('textbox')).toHaveAttribute('rows', '6');
  });

  it('forwards the name attribute', () => {
    render(<TextArea id="n" name="description" />);
    expect(screen.getByRole('textbox')).toHaveAttribute('name', 'description');
  });
});
