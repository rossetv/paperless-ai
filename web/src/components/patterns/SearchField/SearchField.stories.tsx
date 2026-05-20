import type { Meta, StoryObj } from '@storybook/react';
import { SearchField } from './SearchField';

const meta = {
  title: 'Patterns/SearchField',
  component: SearchField,
  parameters: {
    layout: 'padded',
  },
  tags: ['autodocs'],
  argTypes: {
    disabled: { control: 'boolean' },
    placeholder: { control: 'text' },
    label: { control: 'text' },
  },
} satisfies Meta<typeof SearchField>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: {
    id: 'search',
    placeholder: 'Search your documents…',
    onSubmit: (query) => {
      console.log('Search submitted:', query);
    },
  },
};

export const WithLabel: Story = {
  args: {
    id: 'search-labelled',
    label: 'Search',
    placeholder: 'Search your documents…',
    onSubmit: (query) => {
      console.log('Search submitted:', query);
    },
  },
};

export const Disabled: Story = {
  args: {
    id: 'search-disabled',
    placeholder: 'Search unavailable',
    disabled: true,
    onSubmit: () => {
      /* no-op */
    },
  },
};

export const WithValue: Story = {
  args: {
    id: 'search-prefilled',
    value: 'boiler warranty',
    placeholder: 'Search your documents…',
    onSubmit: (query) => {
      console.log('Search submitted:', query);
    },
  },
};
