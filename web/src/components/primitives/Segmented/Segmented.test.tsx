import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Segmented } from './Segmented';

const OPTIONS = [
  { value: 'openai', label: 'OpenAI' },
  { value: 'ollama', label: 'Ollama' },
];

describe('Segmented', () => {
  it('renders a radiogroup with the given label', () => {
    render(
      <Segmented options={OPTIONS} value="openai" onChange={() => {}} label="Provider" />,
    );
    expect(screen.getByRole('radiogroup', { name: 'Provider' })).toBeInTheDocument();
  });

  it('renders one radio per option', () => {
    render(
      <Segmented options={OPTIONS} value="openai" onChange={() => {}} label="Provider" />,
    );
    expect(screen.getByRole('radio', { name: 'OpenAI' })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'Ollama' })).toBeInTheDocument();
  });

  it('marks the selected option as checked', () => {
    render(
      <Segmented options={OPTIONS} value="ollama" onChange={() => {}} label="Provider" />,
    );
    expect(screen.getByRole('radio', { name: 'Ollama' })).toHaveAttribute(
      'aria-checked',
      'true',
    );
    expect(screen.getByRole('radio', { name: 'OpenAI' })).toHaveAttribute(
      'aria-checked',
      'false',
    );
  });

  it('calls onChange with the option value when a segment is clicked', async () => {
    const onChange = vi.fn();
    render(
      <Segmented options={OPTIONS} value="openai" onChange={onChange} label="Provider" />,
    );
    await userEvent.click(screen.getByRole('radio', { name: 'Ollama' }));
    expect(onChange).toHaveBeenCalledWith('ollama');
  });

  it('does not call onChange when the already-selected segment is clicked', async () => {
    const onChange = vi.fn();
    render(
      <Segmented options={OPTIONS} value="openai" onChange={onChange} label="Provider" />,
    );
    await userEvent.click(screen.getByRole('radio', { name: 'OpenAI' }));
    expect(onChange).not.toHaveBeenCalled();
  });

  it('does not call onChange when disabled', async () => {
    const onChange = vi.fn();
    render(
      <Segmented
        options={OPTIONS}
        value="openai"
        onChange={onChange}
        label="Provider"
        disabled
      />,
    );
    await userEvent.click(screen.getByRole('radio', { name: 'Ollama' }));
    expect(onChange).not.toHaveBeenCalled();
  });

  it('forwards a custom className', () => {
    render(
      <Segmented
        options={OPTIONS}
        value="openai"
        onChange={() => {}}
        label="Provider"
        className="extra"
      />,
    );
    expect(screen.getByRole('radiogroup').className).toContain('extra');
  });

  it('keeps only the checked radio in the tab order', () => {
    render(
      <Segmented options={OPTIONS} value="ollama" onChange={() => {}} label="Provider" />,
    );
    expect(screen.getByRole('radio', { name: 'Ollama' })).toHaveAttribute('tabindex', '0');
    expect(screen.getByRole('radio', { name: 'OpenAI' })).toHaveAttribute('tabindex', '-1');
  });

  it('arrow keys move focus to the next enabled option, wrap, and select it', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const options = [
      { value: 'a', label: 'A' },
      { value: 'b', label: 'B', disabled: true },
      { value: 'c', label: 'C' },
    ];
    render(<Segmented options={options} value="a" onChange={onChange} label="L" />);
    screen.getByRole('radio', { name: 'A' }).focus();
    await user.keyboard('{ArrowRight}');
    expect(screen.getByRole('radio', { name: 'C' })).toHaveFocus();
    expect(onChange).toHaveBeenLastCalledWith('c');
    await user.keyboard('{ArrowDown}');
    expect(screen.getByRole('radio', { name: 'A' })).toHaveFocus();
    await user.keyboard('{ArrowLeft}');
    expect(screen.getByRole('radio', { name: 'C' })).toHaveFocus();
  });
});
