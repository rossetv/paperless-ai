import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SettingsSection } from './SettingsSection';
import type { SettingsSection as SectionModel } from '../fieldModel';

const SECTION: SectionModel = {
  id: 'demo',
  title: 'Demo Section',
  subtitle: 'A test section.',
  fields: [
    {
      key: 'TEXT_KEY',
      label: 'Text field',
      hint: 'a text field',
      control: { kind: 'text' },
    },
    {
      key: 'NUM_KEY',
      label: 'Number field',
      hint: 'a number field',
      control: { kind: 'number', min: 0, suffix: 's' },
    },
    {
      key: 'BOOL_KEY',
      label: 'Toggle field',
      hint: 'a toggle field',
      control: { kind: 'toggle' },
    },
    {
      key: 'SEG_KEY',
      label: 'Segmented field',
      hint: 'a segmented field',
      control: {
        kind: 'segmented',
        options: [
          { value: 'a', label: 'A' },
          { value: 'b', label: 'B' },
        ],
      },
    },
    {
      key: 'SECRET_KEY',
      label: 'Secret field',
      hint: 'a secret field',
      control: { kind: 'secret' },
      secret: true,
    },
    {
      key: 'LIST_KEY',
      label: 'List field',
      hint: 'a list field',
      control: { kind: 'list' },
    },
  ],
};

const VALUES = {
  TEXT_KEY: 'hello',
  NUM_KEY: 30,
  BOOL_KEY: false,
  SEG_KEY: 'a',
  SECRET_KEY: '••••mask',
  LIST_KEY: ['x', 'y'],
};

function renderSection(overrides: Partial<Parameters<typeof SettingsSection>[0]> = {}) {
  return render(
    <SettingsSection
      section={SECTION}
      values={VALUES}
      onChange={() => {}}
      {...overrides}
    />,
  );
}

describe('SettingsSection', () => {
  it('renders the section title as a heading', () => {
    renderSection();
    expect(screen.getByRole('heading', { name: 'Demo Section' })).toBeInTheDocument();
  });

  it('renders a text control bound to its value', () => {
    renderSection();
    expect(screen.getByLabelText('Text field')).toHaveValue('hello');
  });

  it('renders a number control bound to its value', () => {
    renderSection();
    expect(screen.getByRole('spinbutton', { name: 'Number field' })).toHaveValue(30);
  });

  it('renders a toggle control reflecting its value', () => {
    renderSection();
    expect(screen.getByRole('switch', { name: 'Toggle field' })).toHaveAttribute(
      'aria-checked',
      'false',
    );
  });

  it('renders a segmented control reflecting its value', () => {
    renderSection();
    expect(screen.getByRole('radio', { name: 'A' })).toHaveAttribute('aria-checked', 'true');
  });

  it('renders a secret field showing the masked value', () => {
    renderSection();
    expect(screen.getByLabelText('Secret field')).toHaveValue('••••mask');
  });

  it('renders a list control showing each item as a pill', () => {
    renderSection();
    expect(screen.getByText('x')).toBeInTheDocument();
    expect(screen.getByText('y')).toBeInTheDocument();
  });

  it('reports a text edit via onChange with the key and value', async () => {
    const onChange = vi.fn();
    renderSection({ onChange });
    await userEvent.type(screen.getByLabelText('Text field'), '!');
    expect(onChange).toHaveBeenCalledWith('TEXT_KEY', 'hello!');
  });

  it('reports a number increment via onChange', async () => {
    const onChange = vi.fn();
    renderSection({ onChange });
    await userEvent.click(screen.getByRole('button', { name: 'Increase Number field' }));
    expect(onChange).toHaveBeenCalledWith('NUM_KEY', 31);
  });

  it('reports a toggle flip via onChange', async () => {
    const onChange = vi.fn();
    renderSection({ onChange });
    await userEvent.click(screen.getByRole('switch', { name: 'Toggle field' }));
    expect(onChange).toHaveBeenCalledWith('BOOL_KEY', true);
  });

  it('reports a new list item via onChange when Add is clicked', async () => {
    const onChange = vi.fn();
    renderSection({ onChange });
    await userEvent.type(screen.getByLabelText('List field'), 'z');
    await userEvent.click(screen.getByRole('button', { name: 'Add' }));
    // Existing value is ['x', 'y']; adding 'z' produces ['x', 'y', 'z'].
    expect(onChange).toHaveBeenLastCalledWith('LIST_KEY', ['x', 'y', 'z']);
  });

  it('reports a secret replacement via onChange once Replace is used', async () => {
    const onChange = vi.fn();
    renderSection({ onChange });
    await userEvent.click(screen.getByRole('button', { name: /replace/i }));
    await userEvent.type(screen.getByLabelText('Secret field'), 'z');
    expect(onChange).toHaveBeenCalledWith('SECRET_KEY', 'z');
  });

  it('shows a re-index note for a key in reindexKeys', () => {
    renderSection({ reindexKeys: new Set(['NUM_KEY']) });
    expect(screen.getByText(/requires re-indexing all documents/i)).toBeInTheDocument();
  });

  it('shows no re-index note when no key needs one', () => {
    renderSection();
    expect(screen.queryByText(/requires re-indexing/i)).not.toBeInTheDocument();
  });
});
