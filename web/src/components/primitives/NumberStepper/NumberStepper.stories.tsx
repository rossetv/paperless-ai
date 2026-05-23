import type { Meta, StoryObj } from '@storybook/react';
import { useState } from 'react';
import { NumberStepper } from './NumberStepper';

const meta = {
  title: 'Primitives/NumberStepper',
  component: NumberStepper,
  tags: ['autodocs'],
} satisfies Meta<typeof NumberStepper>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Plain: Story = {
  args: { value: 10, label: 'Top K', onChange: () => {} },
};

export const WithSuffix: Story = {
  args: { value: 300, label: 'Reconcile interval', suffix: 's', onChange: () => {} },
};

export const Disabled: Story = {
  args: { value: 1536, label: 'Embedding dimensions', disabled: true, onChange: () => {} },
};

/** Interactive — clamped to 0–3, demonstrating the min/max guard. */
export const Clamped: Story = {
  args: { value: 1, label: 'Max refinements', min: 0, max: 3, onChange: () => {} },
  render: (args) => {
    const [value, setValue] = useState(args.value);
    return <NumberStepper {...args} value={value} onChange={setValue} />;
  },
};
