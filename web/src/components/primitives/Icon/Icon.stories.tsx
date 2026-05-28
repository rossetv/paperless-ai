import type { Meta, StoryObj } from '@storybook/react';
import { Icon } from './Icon';
import type { IconName } from './Icon';

const ALL_NAMES: IconName[] = [
  'search',
  'close',
  'document',
  'external-link',
  'chevron-down',
  'chevron-right',
  'info',
  'check',
  'warning',
  'tag',
  'link',
  'sparkle',
  'waves',
  'eye',
  'eye-off',
  'paragraph',
  'lightning',
  'list-lines',
  'users',
  'key',
  'library',
  'index',
  'settings',
];

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
      options: ALL_NAMES satisfies IconName[],
    },
    size: {
      control: 'radio',
      options: ['small', 'medium', 'large', 'xlarge'],
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
  render: () => (
    <div
      style={{
        display: 'flex',
        flexWrap: 'wrap',
        gap: 'var(--spacing-14)',
        alignItems: 'center',
        padding: 'var(--spacing-14)',
      }}
    >
      {ALL_NAMES.map((name) => (
        <div
          key={name}
          style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: 'var(--spacing-2)',
          }}
        >
          <Icon name={name} size="medium" />
          <span style={{ fontSize: 'var(--font-size-micro)', fontFamily: 'monospace' }}>{name}</span>
        </div>
      ))}
    </div>
  ),
};

export const Sizes: StoryObj = {
  render: () => (
    <div style={{ display: 'flex', gap: 'var(--spacing-14)', alignItems: 'center' }}>
      <Icon name="search" size="small" />
      <Icon name="search" size="medium" />
      <Icon name="search" size="large" />
      <Icon name="search" size="xlarge" />
    </div>
  ),
};
