import type { Meta, StoryObj } from '@storybook/react';
import { Page } from './Page';

const meta = {
  title: 'Layout/Page',
  component: Page,
  parameters: {
    layout: 'fullscreen',
  },
  tags: ['autodocs'],
} satisfies Meta<typeof Page>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: {
    children: (
      <div style={{ padding: '2rem', fontFamily: 'var(--font-text)' }}>
        <h1>Page content</h1>
        <p>This is wrapped in the Page layout component.</p>
      </div>
    ),
  },
};

export const WithCustomClass: Story = {
  args: {
    className: 'my-page',
    children: (
      <div style={{ padding: '2rem', fontFamily: 'var(--font-text)' }}>
        <p>Page with a custom className.</p>
      </div>
    ),
  },
};
