import type { Meta, StoryObj } from '@storybook/react';
import { SectionCard } from './SectionCard';

const meta = {
  title: 'Primitives/SectionCard',
  component: SectionCard,
  tags: ['autodocs'],
} satisfies Meta<typeof SectionCard>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Basic: Story = {
  args: {
    title: 'LLM Provider',
    subtitle: 'The model used for OCR, classification, planning and synthesis.',
    id: 'llm',
    children: <p style={{ margin: 0 }}>Rows go here.</p>,
  },
};

export const WithIconAndBadge: Story = {
  args: {
    title: 'Paperless Connection',
    subtitle: 'The Paperless-ngx instance your daemons read from.',
    id: 'paperless',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none"
        stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
        <path d="M7 4h7l5 5v11a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1z" />
        <path d="M14 4v5h5" />
      </svg>
    ),
    badge: (
      <span style={{ color: 'var(--colour-status-ok-fg)', fontSize: 'var(--font-size-micro)' }}>
        Connected
      </span>
    ),
    children: <p style={{ margin: 0 }}>Rows go here.</p>,
  },
};
