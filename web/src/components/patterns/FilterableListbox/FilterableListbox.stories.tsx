import { useState } from 'react';
import type { Meta, StoryObj } from '@storybook/react';
import { FilterableListbox, type FilterableItem } from './FilterableListbox';

const CORRESPONDENTS: FilterableItem<number>[] = [
  { value: 1, label: 'HMRC', meta: '42 docs' },
  { value: 2, label: 'British Gas', meta: '18 docs' },
  { value: 3, label: 'Thames Water', meta: '9 docs' },
  { value: 4, label: 'Santander', meta: '27 docs' },
  { value: 5, label: 'Royal Mail', meta: '3 docs' },
];

const meta = {
  title: 'Patterns/FilterableListbox',
  component: FilterableListbox,
  parameters: { layout: 'padded' },
} satisfies Meta<typeof FilterableListbox>;

export default meta;
type Story = StoryObj<typeof meta>;

/**
 * Single-select with a create-new row and a Clear affordance — the
 * TaxonomyCombobox shape. Type to filter, ArrowUp/Down to move, Enter to pick,
 * Escape or a click outside to close. Typing an unknown name reveals "Create …".
 */
export const SingleSelect: Story = {
  args: {
    id: 'correspondent',
    items: CORRESPONDENTS,
    value: 1,
    triggerLabel: '—',
    onSelect: () => { /* story — noop */ },
  },
  render: function SingleSelectStory() {
    const [selected, setSelected] = useState<number | null>(1);
    const selectedItem = CORRESPONDENTS.find((c) => c.value === selected);
    return (
      <div style={{ maxWidth: 320 }}>
        <FilterableListbox<number>
          id="correspondent"
          items={CORRESPONDENTS}
          value={selected}
          triggerLabel="—"
          selectedLabel={selectedItem?.label}
          placeholder="Search correspondents…"
          clearOption={
            selected !== null
              ? { label: 'Clear', onClear: () => setSelected(null) }
              : undefined
          }
          onSelect={(value) => setSelected(value)}
          onCreate={(name) => {
            console.log('Create correspondent:', name);
          }}
        />
      </div>
    );
  },
};

/**
 * Multi-select — the TagEditor shape. The list stays open after each pick and
 * the chosen tag is removed from `items`, so you can add several in a row. The
 * caller renders the selected chips itself; here they are shown above.
 */
export const MultiSelect: Story = {
  args: {
    id: 'tags',
    items: [],
    value: [],
    multiple: true,
    triggerLabel: '+ Add tag',
    onSelect: () => { /* story — noop */ },
  },
  render: function MultiSelectStory() {
    const ALL: FilterableItem<number>[] = [
      { value: 10, label: 'invoice', meta: '120 docs' },
      { value: 11, label: 'receipt', meta: '64 docs' },
      { value: 12, label: 'contract', meta: '8 docs' },
      { value: 13, label: 'statement', meta: '31 docs' },
      { value: 14, label: 'tax', meta: '17 docs' },
    ];
    const [selected, setSelected] = useState<number[]>([10]);
    const available = ALL.filter((t) => !selected.includes(t.value));
    return (
      <div style={{ maxWidth: 360, display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        {selected.map((id) => {
          const tag = ALL.find((t) => t.value === id);
          return (
            <span key={id} style={{ background: 'var(--colour-button-active-bg)', padding: '2px 8px', borderRadius: 6 }}>
              {tag?.label}
            </span>
          );
        })}
        <FilterableListbox<number>
          id="tags"
          multiple
          items={available}
          value={selected}
          triggerLabel="+ Add tag"
          placeholder="Search tags…"
          onSelect={(value) => setSelected((prev) => [...prev, value])}
          onCreate={(name) => {
            console.log('Create tag:', name);
          }}
        />
      </div>
    );
  },
};

/** Single-select with no create-new — picking only from a fixed set. */
export const NoCreate: Story = {
  args: {
    id: 'fixed',
    items: CORRESPONDENTS,
    value: null,
    triggerLabel: 'Choose a correspondent',
    onSelect: () => { /* story — noop */ },
  },
  render: function NoCreateStory() {
    const [selected, setSelected] = useState<number | null>(null);
    const selectedItem = CORRESPONDENTS.find((c) => c.value === selected);
    return (
      <div style={{ maxWidth: 320 }}>
        <FilterableListbox<number>
          id="fixed"
          items={CORRESPONDENTS}
          value={selected}
          triggerLabel="Choose a correspondent"
          selectedLabel={selectedItem?.label}
          onSelect={(value) => setSelected(value)}
        />
      </div>
    );
  },
};
