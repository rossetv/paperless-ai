import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { FieldControl } from './FieldControl';
import type { SettingsField, ConfigValue } from '../fieldModel';

// ── Fixtures ─────────────────────────────────────────────────────────────────

const textField: SettingsField = {
  key: 'MY_TEXT',
  label: 'Text field',
  hint: 'A text field',
  control: { kind: 'text' },
};

const numberField: SettingsField = {
  key: 'MY_NUMBER',
  label: 'Number field',
  hint: 'A number field',
  control: { kind: 'number', min: 0, max: 100 },
};

const toggleField: SettingsField = {
  key: 'MY_TOGGLE',
  label: 'Toggle field',
  hint: 'A toggle field',
  control: { kind: 'toggle' },
};

const segmentedField: SettingsField = {
  key: 'MY_SEG',
  label: 'Segmented field',
  hint: 'A segmented field',
  control: {
    kind: 'segmented',
    options: [
      { value: 'a', label: 'Option A' },
      { value: 'b', label: 'Option B' },
    ],
  },
};

const secretField: SettingsField = {
  key: 'MY_SECRET',
  label: 'Secret field',
  hint: 'A secret field',
  control: { kind: 'secret' },
  secret: true,
};

const listField: SettingsField = {
  key: 'MY_LIST',
  label: 'List field',
  hint: 'A list field',
  control: { kind: 'list' },
};

const selectField: SettingsField = {
  key: 'MY_SELECT',
  label: 'Select field',
  hint: 'A select field',
  control: {
    kind: 'select',
    options: [
      { value: 'gpt-5.4-nano', label: 'gpt-5.4-nano' },
      { value: 'gpt-5.4', label: 'gpt-5.4' },
    ],
  },
};

const selectWithReasoningField: SettingsField = {
  key: 'MY_MODEL',
  label: 'Model',
  hint: 'Which model to use',
  control: {
    kind: 'select',
    options: [
      { value: 'gpt-5.4-nano', label: 'gpt-5.4-nano' },
      { value: 'gpt-5.4', label: 'gpt-5.4' },
    ],
    reasoningKey: 'MY_MODEL_REASONING',
    reasoningOptions: [
      { value: 'low', label: 'Low' },
      { value: 'medium', label: 'Medium' },
      { value: 'high', label: 'High' },
    ],
  },
};

function noop(_key: string, _value: ConfigValue | null) {}

// ── Basic dispatch ────────────────────────────────────────────────────────────

describe('FieldControl', () => {
  it('renders a text input for kind=text', () => {
    render(
      <FieldControl
        field={textField}
        value="hello"
        onChange={noop}
        controlId="setting-MY_TEXT"
      />,
    );
    expect(screen.getByDisplayValue('hello')).toBeInTheDocument();
  });

  it('renders a spinbutton for kind=number', () => {
    render(
      <FieldControl
        field={numberField}
        value={42}
        onChange={noop}
        controlId="setting-MY_NUMBER"
      />,
    );
    expect(screen.getByRole('spinbutton', { name: 'Number field' })).toHaveValue(42);
  });

  it('renders a switch for kind=toggle', () => {
    render(
      <FieldControl
        field={toggleField}
        value={true}
        onChange={noop}
      />,
    );
    expect(screen.getByRole('switch', { name: 'Toggle field' })).toHaveAttribute('aria-checked', 'true');
  });

  it('renders a radiogroup for kind=segmented', () => {
    render(
      <FieldControl
        field={segmentedField}
        value="a"
        onChange={noop}
      />,
    );
    expect(screen.getByRole('radio', { name: 'Option A' })).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByRole('radio', { name: 'Option B' })).toHaveAttribute('aria-checked', 'false');
  });

  it('renders a masked input for kind=secret', () => {
    render(
      <FieldControl
        field={secretField}
        value="********"
        onChange={noop}
        controlId="setting-MY_SECRET"
      />,
    );
    expect(screen.getByLabelText('Secret field')).toHaveValue('********');
  });

  it('renders a list field for kind=list', () => {
    render(
      <FieldControl
        field={listField}
        value={['x', 'y']}
        onChange={noop}
        controlId="setting-MY_LIST"
      />,
    );
    expect(screen.getByText('x')).toBeInTheDocument();
    expect(screen.getByText('y')).toBeInTheDocument();
  });

  it('renders a select combobox for kind=select without reasoningKey', () => {
    render(
      <FieldControl
        field={selectField}
        value="gpt-5.4-nano"
        onChange={noop}
        controlId="setting-MY_SELECT"
      />,
    );
    expect(screen.getByRole('combobox', { name: 'Select field' })).toBeInTheDocument();
    // No reasoning segmented is present.
    expect(screen.queryByRole('radiogroup', { name: 'Reasoning' })).not.toBeInTheDocument();
  });

  // ── Composite model+reasoning ─────────────────────────────────────────────

  it('renders a Reasoning segmented beneath a select with reasoningKey', () => {
    render(
      <FieldControl
        field={selectWithReasoningField}
        value="gpt-5.4-nano"
        onChange={noop}
        reasoningValue="medium"
        controlId="setting-MY_MODEL"
      />,
    );
    expect(screen.getByRole('combobox', { name: 'Model' })).toBeInTheDocument();
    expect(screen.getByRole('radiogroup', { name: 'Reasoning' })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'Medium' })).toHaveAttribute('aria-checked', 'true');
  });

  it('fires onChange with the reasoningKey when a reasoning option is selected', async () => {
    const onChange = vi.fn();
    render(
      <FieldControl
        field={selectWithReasoningField}
        value="gpt-5.4-nano"
        onChange={onChange}
        reasoningValue="low"
        controlId="setting-MY_MODEL"
      />,
    );
    await userEvent.click(screen.getByRole('radio', { name: 'High' }));
    expect(onChange).toHaveBeenCalledWith('MY_MODEL_REASONING', 'high');
  });

  it('fires onChange with the field key when the model select changes', async () => {
    const onChange = vi.fn();
    render(
      <FieldControl
        field={selectWithReasoningField}
        value="gpt-5.4-nano"
        onChange={onChange}
        reasoningValue="low"
        controlId="setting-MY_MODEL"
      />,
    );
    await userEvent.selectOptions(
      screen.getByRole('combobox', { name: 'Model' }),
      'gpt-5.4',
    );
    expect(onChange).toHaveBeenCalledWith('MY_MODEL', 'gpt-5.4');
  });

  it('renders no Reasoning segmented when reasoningKey is set but reasoningValue is not passed', () => {
    // When the parent does not supply reasoningValue, the composite still renders
    // the segmented — it just defaults to empty string for no selection.
    render(
      <FieldControl
        field={selectWithReasoningField}
        value="gpt-5.4-nano"
        onChange={noop}
        controlId="setting-MY_MODEL"
      />,
    );
    // Reasoning segmented should still render (reasoningValue defaults to '').
    expect(screen.getByRole('radiogroup', { name: 'Reasoning' })).toBeInTheDocument();
  });

  // ── onChange wiring ───────────────────────────────────────────────────────

  it('fires onChange with the field key and new value for a text change', async () => {
    const onChange = vi.fn();
    render(
      <FieldControl
        field={textField}
        value="hello"
        onChange={onChange}
        controlId="setting-MY_TEXT"
      />,
    );
    await userEvent.type(screen.getByDisplayValue('hello'), '!');
    expect(onChange).toHaveBeenCalledWith('MY_TEXT', 'hello!');
  });
});
