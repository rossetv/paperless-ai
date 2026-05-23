import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SettingsListField } from './SettingsListField';

function renderField(props: Partial<Parameters<typeof SettingsListField>[0]> = {}) {
  const defaults = {
    id: 'models',
    label: 'Model list',
    value: [] as string[],
    onChange: () => {},
  };
  return render(<SettingsListField {...defaults} {...props} />);
}

describe('SettingsListField', () => {
  it('renders an add input labelled by the label prop', () => {
    renderField();
    expect(screen.getByLabelText('Model list')).toBeInTheDocument();
  });

  it('renders each existing item as a numbered pill', () => {
    renderField({ value: ['gpt-5.4-mini', 'gpt-5.4'] });
    expect(screen.getByText('gpt-5.4-mini')).toBeInTheDocument();
    expect(screen.getByText('gpt-5.4')).toBeInTheDocument();
    // Numbers
    expect(screen.getByText('1')).toBeInTheDocument();
    expect(screen.getByText('2')).toBeInTheDocument();
  });

  it('calls onChange with the new item appended when Add is clicked', async () => {
    const onChange = vi.fn();
    renderField({ value: ['a'], onChange });
    await userEvent.type(screen.getByLabelText('Model list'), 'b');
    await userEvent.click(screen.getByRole('button', { name: 'Add' }));
    expect(onChange).toHaveBeenCalledWith(['a', 'b']);
  });

  it('calls onChange with the new item appended when Enter is pressed', async () => {
    const onChange = vi.fn();
    renderField({ value: [], onChange });
    await userEvent.type(screen.getByLabelText('Model list'), 'x{Enter}');
    expect(onChange).toHaveBeenCalledWith(['x']);
  });

  it('does not call onChange when the input is empty and Add is clicked', async () => {
    const onChange = vi.fn();
    renderField({ value: [], onChange });
    // Add button is disabled when input is empty — no click should fire
    const btn = screen.getByRole('button', { name: 'Add' });
    expect(btn).toBeDisabled();
  });

  it('calls onChange without the removed item when × is clicked', async () => {
    const onChange = vi.fn();
    renderField({ value: ['a', 'b', 'c'], onChange });
    await userEvent.click(screen.getByRole('button', { name: 'Remove b' }));
    expect(onChange).toHaveBeenCalledWith(['a', 'c']);
  });

  it('calls onChange with item moved up when ↑ is clicked', async () => {
    const onChange = vi.fn();
    renderField({ value: ['a', 'b'], onChange });
    await userEvent.click(screen.getByRole('button', { name: 'Move b up' }));
    expect(onChange).toHaveBeenCalledWith(['b', 'a']);
  });

  it('calls onChange with item moved down when ↓ is clicked', async () => {
    const onChange = vi.fn();
    renderField({ value: ['a', 'b'], onChange });
    await userEvent.click(screen.getByRole('button', { name: 'Move a down' }));
    expect(onChange).toHaveBeenCalledWith(['b', 'a']);
  });

  it('disables the up arrow on the first item', () => {
    renderField({ value: ['a', 'b'] });
    expect(screen.getByRole('button', { name: 'Move a up' })).toBeDisabled();
  });

  it('disables the down arrow on the last item', () => {
    renderField({ value: ['a', 'b'] });
    expect(screen.getByRole('button', { name: 'Move b down' })).toBeDisabled();
  });

  it('clears the draft after adding an item', async () => {
    renderField({ value: [], onChange: () => {} });
    const input = screen.getByLabelText('Model list');
    await userEvent.type(input, 'z');
    await userEvent.click(screen.getByRole('button', { name: 'Add' }));
    expect(input).toHaveValue('');
  });

  it('renders no pills when value is an empty array', () => {
    renderField({ value: [] });
    expect(screen.queryByRole('list')).not.toBeInTheDocument();
  });

  it('disables the add input and buttons when disabled', () => {
    renderField({ value: ['x'], disabled: true });
    expect(screen.getByLabelText('Model list')).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Add' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Remove x' })).toBeDisabled();
  });
});
