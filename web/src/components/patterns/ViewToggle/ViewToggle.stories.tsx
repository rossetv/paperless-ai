import React, { useState } from 'react';
import type { Meta, StoryObj } from '@storybook/react';
import { ViewToggle } from './ViewToggle';
import type { LibraryView } from './ViewToggle';

const meta = {
  title: 'Patterns/ViewToggle',
  component: ViewToggle,
  parameters: { layout: 'centered' },
} satisfies Meta<typeof ViewToggle>;

export default meta;
type Story = StoryObj<typeof meta>;

/** Interactive — the segment lifts as you click between Grid and List. */
export const Interactive: Story = {
  args: { value: 'grid', onChange: () => {} },
  render: function Render() {
    const [view, setView] = useState<LibraryView>('grid');
    return <ViewToggle value={view} onChange={setView} />;
  },
};

/** The List view selected. */
export const ListSelected: Story = {
  args: { value: 'list', onChange: () => {} },
};
