import type { Meta, StoryObj } from '@storybook/react';
import { Brand } from './Brand';

const meta = {
  title: 'Primitives/Brand',
  component: Brand,
  parameters: { layout: 'centered' },
  tags: ['autodocs'],
  argTypes: {
    size: { control: { type: 'range', min: 16, max: 64, step: 2 } },
    color: { control: 'color' },
  },
} satisfies Meta<typeof Brand>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = { args: {} };

export const Large: Story = { args: { size: 40, color: '#fff' }, parameters: { backgrounds: { default: 'dark' } } };

export const OnDark: Story = {
  args: { size: 26, color: '#fff' },
  parameters: { backgrounds: { default: 'dark' } },
};

export const WithWordmark: StoryObj = {
  render: () => (
    <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--spacing-7)', color: '#fff', background: '#000', padding: 'var(--spacing-13)' }}>
      <Brand size={22} color="#fff" />
      <span style={{ fontFamily: 'var(--font-text)', fontSize: 'var(--font-size-nav)', fontWeight: 500, letterSpacing: '-0.1px' }}>
        Paperless<span style={{ opacity: 0.55, fontWeight: 400 }}>AI</span>
      </span>
    </div>
  ),
};
