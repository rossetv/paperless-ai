import type { Meta, StoryObj } from '@storybook/react';
import { ConnectionCard } from './ConnectionCard';

const meta = {
  title: 'Features/Settings/ConnectionCard',
  component: ConnectionCard,
  tags: ['autodocs'],
  args: {
    glyph: 'P',
    glyphTone: 'blue',
    title: 'Paperless-ngx',
    subtitle: 'Where the daemons reach Paperless',
    onTest: () => undefined,
    children: (
      <p style={{ padding: '12px 0', color: 'var(--colour-text-secondary)' }}>
        Card body (fields rendered here in production)
      </p>
    ),
  },
} satisfies Meta<typeof ConnectionCard>;

export default meta;
type Story = StoryObj<typeof meta>;

export const StatusOk: Story = {
  args: { status: { tone: 'ok', label: 'Connected' }, defaultOpen: true },
};

export const StatusErr: Story = {
  args: {
    status: { tone: 'err', label: 'Connection refused' },
    glyph: 'AI',
    glyphTone: 'teal',
    title: 'OpenAI',
    subtitle: 'Required for every process',
  },
};

export const StatusOff: Story = {
  args: {
    status: { tone: 'off', label: 'Not configured' },
    glyph: 'Ll',
    glyphTone: 'grey',
    title: 'Ollama',
    subtitle: 'Ignored when the provider is OpenAI',
  },
};

export const StatusUntested: Story = {
  args: { status: { tone: 'untested', label: 'Untested' } },
};
