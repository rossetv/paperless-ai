import type { Meta, StoryObj } from '@storybook/react';
import { Section } from './Section';

const meta = {
  title: 'Layout/Section',
  component: Section,
  parameters: {
    layout: 'fullscreen',
  },
  tags: ['autodocs'],
  argTypes: {
    spacious: { control: 'boolean' },
  },
} satisfies Meta<typeof Section>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: {
    children: (
      <div style={{ background: '#e0e0e0', padding: '0.5rem', fontFamily: 'sans-serif' }}>
        Default section — compact vertical padding.
      </div>
    ),
  },
};

export const Spacious: Story = {
  args: {
    spacious: true,
    children: (
      <div style={{ background: '#e0e0e0', padding: '0.5rem', fontFamily: 'sans-serif' }}>
        Spacious section — cinematic breathing room (DESIGN.md §5).
      </div>
    ),
  },
};
