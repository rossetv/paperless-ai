import type { Meta, StoryObj } from '@storybook/react';
import { Link } from './Link';

const meta = {
  title: 'Primitives/Link',
  component: Link,
  parameters: {
    layout: 'centered',
  },
  tags: ['autodocs'],
  argTypes: {
    variant: {
      control: 'radio',
      options: ['default', 'inline', 'on-dark'],
    },
    external: { control: 'boolean' },
  },
} satisfies Meta<typeof Link>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: {
    href: '#',
    children: 'Learn more',
    variant: 'default',
  },
};

export const Inline: Story = {
  args: {
    href: '#',
    children: 'inline body link',
    variant: 'inline',
  },
  decorators: [
    // Plain <p> — global.css (loaded in preview.ts) supplies body typography.
    (Story) => (
      <p>
        This paragraph contains an <Story /> within body copy.
      </p>
    ),
  ],
};

export const OnDark: Story = {
  args: {
    href: '#',
    children: 'Learn more',
    variant: 'on-dark',
  },
  parameters: {
    backgrounds: { default: 'dark' },
  },
};

export const External: Story = {
  args: {
    href: 'https://apple.com',
    children: 'Visit Apple',
    external: true,
  },
};

export const AllVariants: StoryObj = {
  render: () => (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--spacing-14)' }}>
      <Link href="#">Default link</Link>
      <Link href="#" variant="inline">Inline link</Link>
      <div style={{ background: 'var(--colour-surface-dark)', padding: 'var(--spacing-14)' }}>
        <Link href="#" variant="on-dark">On-dark link</Link>
      </div>
      <Link href="https://example.com" external>External link (opens new tab)</Link>
    </div>
  ),
};
