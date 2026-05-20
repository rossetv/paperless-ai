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

const SampleContent = () => (
  <>
    <h3 style={{ margin: '0 0 0.5rem', fontFamily: 'sans-serif' }}>Card title</h3>
    <p style={{ margin: 0, fontFamily: 'sans-serif', fontSize: '14px' }}>
      A surface container holding arbitrary content.
    </p>
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
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem', width: '300px' }}>
      <Card>Default surface (flat)</Card>
      <Card elevated>Default surface (elevated)</Card>
      <div style={{ background: '#000', padding: '1rem', borderRadius: '8px' }}>
        <Card surface="dark-1" elevated>Dark surface 1</Card>
      </div>
    </div>
  ),
};
