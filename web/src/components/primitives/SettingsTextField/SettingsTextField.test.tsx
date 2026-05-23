import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SettingsTextField } from './SettingsTextField';

describe('SettingsTextField', () => {
  it('renders a textbox carrying the current value', () => {
    render(
      <SettingsTextField id="url" label="Server URL" value="http://x" onChange={() => {}} />,
    );
    expect(screen.getByRole('textbox', { name: 'Server URL' })).toHaveValue('http://x');
  });

  it('reports each keystroke via onChange', async () => {
    const onChange = vi.fn();
    render(
      <SettingsTextField id="url" label="Server URL" value="" onChange={onChange} />,
    );
    await userEvent.type(screen.getByRole('textbox'), 'a');
    expect(onChange).toHaveBeenCalledWith('a');
  });

  it('renders the placeholder when given', () => {
    render(
      <SettingsTextField
        id="c"
        label="Country"
        value=""
        onChange={() => {}}
        placeholder="Leave empty to skip"
      />,
    );
    expect(screen.getByPlaceholderText('Leave empty to skip')).toBeInTheDocument();
  });

  it('renders the inline suffix slot', () => {
    render(
      <SettingsTextField
        id="t"
        label="Token"
        value="x"
        onChange={() => {}}
        suffix={<button type="button">Reveal</button>}
      />,
    );
    expect(screen.getByRole('button', { name: 'Reveal' })).toBeInTheDocument();
  });

  it('honours the type prop (password)', () => {
    render(
      <SettingsTextField
        id="t"
        label="Token"
        value="x"
        onChange={() => {}}
        type="password"
      />,
    );
    // A password input has no textbox role — query by the label association.
    expect(screen.getByLabelText('Token')).toHaveAttribute('type', 'password');
  });

  it('does not call onChange when read-only', async () => {
    const onChange = vi.fn();
    render(
      <SettingsTextField
        id="p"
        label="Path"
        value="/data/index.db"
        onChange={onChange}
        readOnly
      />,
    );
    await userEvent.type(screen.getByRole('textbox'), 'x');
    expect(onChange).not.toHaveBeenCalled();
  });

  it('applies the monospace modifier class when mono is set', () => {
    render(
      <SettingsTextField id="u" label="URL" value="x" onChange={() => {}} mono />,
    );
    expect(screen.getByRole('textbox').className).toMatch(/mono/i);
  });

  it('forwards a custom className to the wrapper', () => {
    const { container } = render(
      <SettingsTextField
        id="u"
        label="URL"
        value="x"
        onChange={() => {}}
        className="extra"
      />,
    );
    expect(container.firstElementChild?.className).toContain('extra');
  });
});
