import type { Meta, StoryObj } from '@storybook/react';
import { SettingsCard } from './SettingsCard';

const meta = {
  title: 'Primitives/SettingsCard',
  component: SettingsCard,
  tags: ['autodocs'],
} satisfies Meta<typeof SettingsCard>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Basic: Story = {
  args: {
    title: 'Provider',
    subtitle: 'OpenAI is hosted; Ollama runs locally.',
    children: <p style={{ margin: 'var(--spacing-13) 0' }}>Rows go here.</p>,
  },
};

export const WithHeaderActions: Story = {
  args: {
    title: 'Endpoint',
    subtitle: 'Where the daemons reach Paperless, and where the browser opens documents.',
    headerActions: (
      <button
        type="button"
        style={{
          background: 'transparent',
          border: '1px solid var(--colour-hairline-strong)',
          borderRadius: 'var(--radius-pill)',
          padding: 'var(--spacing-5) var(--spacing-10)',
          fontSize: 'var(--font-size-caption)',
          color: 'var(--colour-text-primary)',
          cursor: 'pointer',
        }}
      >
        Test connection
      </button>
    ),
    children: <p style={{ margin: 'var(--spacing-13) 0' }}>Rows go here.</p>,
  },
};
