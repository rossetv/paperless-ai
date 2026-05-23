import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SettingsSelectField } from './SettingsSelectField';

const OPTIONS = [
  { value: 'gpt-5.4-mini', label: 'gpt-5.4-mini' },
  { value: 'gpt-5.4', label: 'gpt-5.4' },
];

describe('SettingsSelectField', () => {
  it('renders a combobox carrying the current value', () => {
    render(
      <SettingsSelectField
        id="m"
        label="Planner model"
        value="gpt-5.4"
        options={OPTIONS}
        onChange={() => {}}
      />,
    );
    expect(screen.getByRole('combobox', { name: 'Planner model' })).toHaveValue('gpt-5.4');
  });

  it('renders one option per entry', () => {
    render(
      <SettingsSelectField
        id="m"
        label="Planner model"
        value="gpt-5.4-mini"
        options={OPTIONS}
        onChange={() => {}}
      />,
    );
    expect(screen.getByRole('option', { name: 'gpt-5.4-mini' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'gpt-5.4' })).toBeInTheDocument();
  });

  it('reports the chosen value via onChange', async () => {
    const onChange = vi.fn();
    render(
      <SettingsSelectField
        id="m"
        label="Planner model"
        value="gpt-5.4-mini"
        options={OPTIONS}
        onChange={onChange}
      />,
    );
    await userEvent.selectOptions(screen.getByRole('combobox'), 'gpt-5.4');
    expect(onChange).toHaveBeenCalledWith('gpt-5.4');
  });

  it('includes a value not in the options so an unknown current value still shows', () => {
    render(
      <SettingsSelectField
        id="m"
        label="Planner model"
        value="custom-model"
        options={OPTIONS}
        onChange={() => {}}
      />,
    );
    // The current value is always selectable even if absent from `options`.
    expect(screen.getByRole('combobox')).toHaveValue('custom-model');
    expect(screen.getByRole('option', { name: 'custom-model' })).toBeInTheDocument();
  });

  it('is non-interactive when disabled', () => {
    render(
      <SettingsSelectField
        id="m"
        label="Planner model"
        value="gpt-5.4"
        options={OPTIONS}
        onChange={() => {}}
        disabled
      />,
    );
    expect(screen.getByRole('combobox')).toBeDisabled();
  });

  it('forwards a custom className to the wrapper', () => {
    const { container } = render(
      <SettingsSelectField
        id="m"
        label="Planner model"
        value="gpt-5.4"
        options={OPTIONS}
        onChange={() => {}}
        className="extra"
      />,
    );
    expect(container.firstElementChild?.className).toContain('extra');
  });
});
