import type { Meta, StoryObj } from '@storybook/react';
import { Card } from './Card';

const meta = {
  title: 'Primitives/Card',
  component: Card,
  parameters: {
    layout: 'centered',
  },
  tags: ['autodocs'],
  argTypes: {
    as: {
      control: 'radio',
      options: ['div', 'article', 'section', 'aside'],
    },
    surface: {
      control: 'radio',
      options: ['default', 'dark-1', 'dark-2', 'dark-3', 'dark-4', 'dark-5'],
    },
    elevated: { control: 'boolean' },
  },
} satisfies Meta<typeof Card>;

export default meta;
type Story = StoryObj<typeof meta>;

// Plain heading + paragraph — global.css (loaded in preview.ts) supplies the
// type scale, so the story needs no inline typography.
const SampleContent = () => (
  <>
    <h3>Card title</h3>
    <p style={{ margin: 0 }}>A surface container holding arbitrary content.</p>
  </>
);

export const Default: Story = {
  args: {
    children: <SampleContent />,
    surface: 'default',
  },
};

export const Elevated: Story = {
  args: {
    children: <SampleContent />,
    elevated: true,
  },
};

export const DarkSurface: Story = {
  args: {
    children: <SampleContent />,
    surface: 'dark-1',
    elevated: true,
  },
  parameters: {
    backgrounds: { default: 'dark' },
  },
};

export const AsArticle: Story = {
  args: {
    as: 'article',
    children: <SampleContent />,
    elevated: true,
  },
};

export const AllSurfaces: StoryObj = {
  render: () => (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 'var(--spacing-14)',
        width: 'var(--width-empty-state)',
      }}
    >
      <Card>Default surface (flat)</Card>
      <Card elevated>Default surface (elevated)</Card>
      <div
        style={{
          background: 'var(--colour-bg-alt)',
          padding: 'var(--spacing-14)',
          borderRadius: 'var(--radius-standard)',
        }}
      >
        <Card surface="dark-1" elevated>Dark surface 1</Card>
      </div>
    </div>
  ),
};
