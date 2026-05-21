import type { Meta, StoryObj } from '@storybook/react';
import { Icon } from './Icon';
import type { IconName } from './Icon';

const meta = {
  title: 'Primitives/Icon',
  component: Icon,
  parameters: {
    layout: 'centered',
  },
  tags: ['autodocs'],
  argTypes: {
    name: {
      control: 'select',
      options: [
        'search',
        'close',
        'document',
        'external-link',
        'chevron-down',
        'chevron-right',
        'filter',
        'info',
        'check',
        'warning',
        'arrow-left',
        'tag',
      ] satisfies IconName[],
    },
    size: {
      control: 'radio',
      options: ['small', 'medium', 'large'],
    },
  },
} satisfies Meta<typeof Icon>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Search: Story = {
  args: { name: 'search', size: 'medium' },
};

export const Document: Story = {
  args: { name: 'document', size: 'medium' },
};

export const WithLabel: Story = {
  args: { name: 'search', label: 'Search documents', size: 'medium' },
};

export const AllIcons: StoryObj = {
  render: () => {
    const names: IconName[] = [
      'search',
      'close',
      'document',
      'external-link',
      'chevron-down',
      'chevron-right',
      'filter',
      'info',
      'check',
      'warning',
      'arrow-left',
      'tag',
    ];
    return (
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: 'var(--spacing-14)',
          alignItems: 'center',
          padding: 'var(--spacing-14)',
        }}
      >
        {names.map((name) => (
          <div
            key={name}
            style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 'var(--spacing-2)' }}
          >
            <Icon name={name} size="medium" />
            <span style={{ fontSize: 'var(--font-size-micro)', fontFamily: 'monospace' }}>{name}</span>
          </div>
        ))}
      </div>
    );
  },
};

export const Sizes: StoryObj = {
  render: () => (
    <div style={{ display: 'flex', gap: 'var(--spacing-14)', alignItems: 'center' }}>
      <Icon name="search" size="small" />
      <Icon name="search" size="medium" />
      <Icon name="search" size="large" />
    </div>
  ),
};
