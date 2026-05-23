import type { Meta, StoryObj } from '@storybook/react';
import { useState } from 'react';
import { Toggle } from './Toggle';

const meta = {
  title: 'Primitives/Toggle',
  component: Toggle,
  tags: ['autodocs'],
} satisfies Meta<typeof Toggle>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Off: Story = {
  args: { checked: false, label: 'Verbose logging', onChange: () => {} },
};

export const On: Story = {
  args: { checked: true, label: 'Verbose logging', onChange: () => {} },
};

export const Disabled: Story = {
  args: { checked: true, label: 'Verbose logging', disabled: true, onChange: () => {} },
};

/** Interactive — flips its own state. */
export const Interactive: Story = {
  args: { checked: false, label: 'Verbose logging', onChange: () => {} },
  render: (args) => {
    const [on, setOn] = useState(args.checked);
    return <Toggle {...args} checked={on} onChange={setOn} />;
  },
};
