import type { Meta, StoryObj } from '@storybook/react';
import { SettingsBlock } from './SettingsBlock';
import { SettingsCard } from '../SettingsCard/SettingsCard';

const meta = {
  title: 'Primitives/SettingsBlock',
  component: SettingsBlock,
  tags: ['autodocs'],
} satisfies Meta<typeof SettingsBlock>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Basic: Story = {
  args: {
    title: 'LLM Provider',
    subtitle: 'The model used for OCR, classification, planning and synthesis.',
    id: 'llm',
    children: (
      <SettingsCard title="Provider" subtitle="OpenAI is hosted; Ollama runs locally.">
        <p style={{ margin: 'var(--spacing-13) 0', color: 'var(--colour-text-tertiary)' }}>
          Rows go here.
        </p>
      </SettingsCard>
    ),
  },
};

export const MultipleCards: Story = {
  args: {
    title: 'Search Server',
    subtitle: 'Tune the agentic search pipeline — planning, retrieval, synthesis.',
    id: 'search',
    children: (
      <>
        <SettingsCard title="Retrieval" subtitle="How many documents the synthesiser sees.">
          <p style={{ margin: 'var(--spacing-13) 0', color: 'var(--colour-text-tertiary)' }}>
            Retrieval rows.
          </p>
        </SettingsCard>
        <SettingsCard title="Models" subtitle="Planner and answer models.">
          <p style={{ margin: 'var(--spacing-13) 0', color: 'var(--colour-text-tertiary)' }}>
            Model rows.
          </p>
        </SettingsCard>
      </>
    ),
  },
};
