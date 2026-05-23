import type { Meta, StoryObj } from '@storybook/react';
import { IndexHealthHero } from './IndexHealthHero';

const meta = {
  title: 'Features/Index/IndexHealthHero',
  component: IndexHealthHero,
  parameters: { layout: 'padded' },
  tags: ['autodocs'],
} satisfies Meta<typeof IndexHealthHero>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Healthy: Story = {
  args: {
    health: {
      healthy: true,
      headline: 'Healthy · ready to serve',
      detail:
        'Schema present · integrity check passed · last reconciled 4 minutes ago. The search server is accepting queries on port 8080.',
      uptime: '14d 6h',
      since: '2026-05-07T00:00:00Z',
    },
  },
};

export const Rebuilding: Story = {
  args: {
    health: {
      healthy: false,
      headline: 'Rebuilding · not ready',
      detail:
        'The index is being rebuilt from scratch; the search server returns 503 until the first reconcile finishes.',
      uptime: '0d 0h',
      since: null,
    },
  },
};
