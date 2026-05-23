import React, { useState } from 'react';
import type { Meta, StoryObj } from '@storybook/react';
import { SortControl } from './SortControl';

const OPTIONS = [
  { value: 'created', label: 'Date added' },
  { value: 'title', label: 'Title' },
  { value: 'correspondent', label: 'Correspondent' },
];

const meta = {
  title: 'Patterns/SortControl',
  component: SortControl,
  parameters: { layout: 'centered' },
} satisfies Meta<typeof SortControl>;

export default meta;
type Story = StoryObj<typeof meta>;

/** Interactive — open the menu and pick a sort field. */
export const Interactive: Story = {
  args: { id: 'sort', label: 'Sort', options: OPTIONS, value: 'created', onChange: () => {} },
  render: function Render() {
    const [value, setValue] = useState('created');
    return (
      <SortControl
        id="sort"
        label="Sort"
        options={OPTIONS}
        value={value}
        onChange={setValue}
      />
    );
  },
};
