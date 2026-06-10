import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SettingsSection } from './SettingsSection';
import type { SettingsSection as SectionModel } from '../fieldModel';

const SECTION: SectionModel = {
  id: 'demo',
  title: 'Demo Section',
  subtitle: 'A test section.',
  groups: [
    {
      id: 'group-a',
      title: 'Group A',
      subtitle: 'First group.',
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
      ],
    },
    {
      id: 'group-b',
      title: 'Group B',
      subtitle: 'Second group.',
      fields: [
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
    },
  ],
};

// ── Section with advanced fields ─────────────────────────────────────────────

const SECTION_WITH_ADVANCED: SectionModel = {
  id: 'advanced-demo',
  title: 'Advanced Demo',
  subtitle: 'Tests advanced disclosure.',
  groups: [
    {
      id: 'group-adv',
      title: 'Group with Advanced',
      fields: [
        {
          key: 'MAIN_FIELD',
          label: 'Main field',
          hint: 'A primary field',
          control: { kind: 'text' },
        },
      ],
      advanced: [
        {
          key: 'ADV_FIELD',
          label: 'Advanced field',
          hint: 'An advanced field',
          control: { kind: 'text' },
        },
      ],
    },
  ],
};

// ── Section with model+reasoning composite ───────────────────────────────────

const SECTION_WITH_REASONING: SectionModel = {
  id: 'reasoning-demo',
  title: 'Reasoning Demo',
  subtitle: 'Tests composite model+reasoning.',
  groups: [
    {
      id: 'group-model',
      title: 'Model Group',
      fields: [
        {
          key: 'MODEL_KEY',
          label: 'Model',
          hint: 'Which model to use',
          control: {
            kind: 'select',
            options: [
              { value: 'gpt-5.4-nano', label: 'gpt-5.4-nano' },
              { value: 'gpt-5.4', label: 'gpt-5.4' },
            ],
            reasoningKey: 'MODEL_REASONING_KEY',
            reasoningOptions: [
              { value: 'low', label: 'Low' },
              { value: 'medium', label: 'Medium' },
              { value: 'high', label: 'High' },
            ],
          },
        },
      ],
    },
  ],
};

const VALUES = {
  TEXT_KEY: 'hello',
  NUM_KEY: 30,
  BOOL_KEY: false,
  SEG_KEY: 'a',
  SECRET_KEY: '********',
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
  it('renders the section title as a level-2 heading', () => {
    renderSection();
    expect(screen.getByRole('heading', { level: 2, name: 'Demo Section' })).toBeInTheDocument();
  });

  it('renders group sub-card headings', () => {
    renderSection();
    expect(screen.getByRole('heading', { level: 3, name: 'Group A' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 3, name: 'Group B' })).toBeInTheDocument();
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
    expect(screen.getByLabelText('Secret field')).toHaveValue('********');
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
    expect(onChange).toHaveBeenLastCalledWith('LIST_KEY', ['x', 'y', 'z']);
  });

  it('reports a secret replacement via onChange once Replace is used', async () => {
    const onChange = vi.fn();
    renderSection({ onChange });
    await userEvent.click(screen.getByRole('button', { name: /replace/i }));
    await userEvent.type(screen.getByLabelText('Secret field'), 'z');
    expect(onChange).toHaveBeenCalledWith('SECRET_KEY', 'z');
  });

  it('shows the reindex pill for a key in reindexKeys', () => {
    renderSection({ reindexKeys: new Set(['NUM_KEY']) });
    expect(screen.getByText(/rebuilds the index on save/i)).toBeInTheDocument();
  });

  it('shows no reindex pill when no key needs one', () => {
    renderSection();
    expect(screen.queryByText(/rebuilds the index on save/i)).not.toBeInTheDocument();
  });

  it('renders groupActions in the matching card header', () => {
    renderSection({
      groupActions: {
        'group-a': <button type="button">Test connection</button>,
      },
    });
    expect(screen.getByRole('button', { name: 'Test connection' })).toBeInTheDocument();
  });

  // ── Advanced disclosure ───────────────────────────────────────────────────

  describe('advanced disclosure', () => {
    function renderAdvanced(overrides: Partial<Parameters<typeof SettingsSection>[0]> = {}) {
      return render(
        <SettingsSection
          section={SECTION_WITH_ADVANCED}
          values={{ MAIN_FIELD: 'main-value', ADV_FIELD: 'adv-value' }}
          onChange={() => {}}
          {...overrides}
        />,
      );
    }

    it('renders the primary field outside the disclosure', () => {
      renderAdvanced();
      expect(screen.getByDisplayValue('main-value')).toBeInTheDocument();
    });

    it('renders a <details> element for the advanced section', () => {
      const { container } = renderAdvanced();
      expect(container.querySelector('details')).not.toBeNull();
    });

    it('renders the Advanced disclosure summary with the field count', () => {
      renderAdvanced();
      // The disclosure summary text is "Advanced · 1".
      expect(screen.getByText(/Advanced · \d/)).toBeInTheDocument();
    });

    it('starts collapsed (no open attribute on details)', () => {
      const { container } = renderAdvanced();
      const details = container.querySelector('details');
      expect(details).not.toHaveAttribute('open');
    });

    it('passes requiresReindex to advanced field rows too', () => {
      renderAdvanced({ reindexKeys: new Set(['ADV_FIELD']) });
      expect(screen.getByText(/rebuilds the index on save/i)).toBeInTheDocument();
    });
  });

  // ── Composite model+reasoning ─────────────────────────────────────────────

  describe('model+reasoning composite', () => {
    function renderReasoning(overrides: Partial<Parameters<typeof SettingsSection>[0]> = {}) {
      return render(
        <SettingsSection
          section={SECTION_WITH_REASONING}
          values={{ MODEL_KEY: 'gpt-5.4-nano', MODEL_REASONING_KEY: 'medium' }}
          onChange={() => {}}
          {...overrides}
        />,
      );
    }

    it('renders the model select combobox', () => {
      renderReasoning();
      expect(screen.getByRole('combobox', { name: 'Model' })).toBeInTheDocument();
    });

    it('renders the Reasoning segmented beneath the model select', () => {
      renderReasoning();
      expect(screen.getByRole('radiogroup', { name: 'Reasoning' })).toBeInTheDocument();
    });

    it('reflects the reasoningValue in the segmented', () => {
      renderReasoning();
      expect(screen.getByRole('radio', { name: 'Medium' })).toHaveAttribute('aria-checked', 'true');
    });

    it('fires onChange with the reasoningKey when a reasoning option is chosen', async () => {
      const onChange = vi.fn();
      renderReasoning({ onChange });
      await userEvent.click(screen.getByRole('radio', { name: 'High' }));
      expect(onChange).toHaveBeenCalledWith('MODEL_REASONING_KEY', 'high');
    });
  });
});
