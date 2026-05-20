import type { Meta, StoryObj } from '@storybook/react';
import { Container } from './Container';

const meta = {
  title: 'Layout/Container',
  component: Container,
  parameters: {
    layout: 'fullscreen',
  },
  tags: ['autodocs'],
} satisfies Meta<typeof Container>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: {
    children: (
      <div style={{ background: '#e0e0e0', padding: '1rem', fontFamily: 'sans-serif' }}>
        Centred content at max 980px width.
      </div>
    ),
  },
};

export const WithCustomClass: Story = {
  args: {
    className: 'my-container',
    children: (
      <div style={{ background: '#e0e0e0', padding: '1rem', fontFamily: 'sans-serif' }}>
        Container with a custom className.
      </div>
    ),
  },
};
