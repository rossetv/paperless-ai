import type { Meta, StoryObj } from '@storybook/react';
import { SettingsTextField } from './SettingsTextField';

const meta = {
  title: 'Primitives/SettingsTextField',
  component: SettingsTextField,
  tags: ['autodocs'],
} satisfies Meta<typeof SettingsTextField>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Plain: Story = {
  args: { id: 'country', label: 'Country', value: 'Ireland', onChange: () => {} },
};

export const Monospace: Story = {
  args: {
    id: 'url',
    label: 'Server URL',
    value: 'http://paperless.lan:8000',
    mono: true,
    onChange: () => {},
  },
};

export const ReadOnly: Story = {
  args: {
    id: 'path',
    label: 'Index database path',
    value: '/data/index.db',
    mono: true,
    readOnly: true,
    onChange: () => {},
  },
};

export const WithSuffix: Story = {
  args: {
    id: 'token',
    label: 'API token',
    value: '••••••••3f9b',
    mono: true,
    onChange: () => {},
    suffix: (
      <button
        type="button"
        style={{
          border: 'none',
          background: 'transparent',
          color: 'var(--colour-link)',
          font: 'inherit',
          cursor: 'pointer',
        }}
      >
        Reveal
      </button>
    ),
  },
};
