import type { Meta, StoryObj } from '@storybook/react';
import { useState } from 'react';
import { Segmented } from './Segmented';

const meta = {
  title: 'Primitives/Segmented',
  component: Segmented,
  tags: ['autodocs'],
} satisfies Meta<typeof Segmented>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Provider: Story = {
  args: {
    label: 'Provider',
    value: 'openai',
    onChange: () => {},
    options: [
      { value: 'openai', label: 'OpenAI' },
      { value: 'ollama', label: 'Ollama' },
    ],
  },
};

export const LogLevel: Story = {
  args: {
    label: 'Log level',
    value: 'INFO',
    onChange: () => {},
    options: [
      { value: 'DEBUG', label: 'DEBUG' },
      { value: 'INFO', label: 'INFO' },
      { value: 'WARNING', label: 'WARNING' },
      { value: 'ERROR', label: 'ERROR' },
    ],
  },
};

/** Interactive — flips its own state. */
export const Interactive: Story = {
  args: { ...Provider.args },
  render: function InteractiveSegmented(args) {
    const [value, setValue] = useState(args.value);
    return <Segmented {...args} value={value} onChange={setValue} />;
  },
};
