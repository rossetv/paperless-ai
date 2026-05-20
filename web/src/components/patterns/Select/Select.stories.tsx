import type { Meta, StoryObj } from '@storybook/react';
import { Select } from './Select';

const FRUIT_OPTIONS = [
  { value: 'apple', label: 'Apple' },
  { value: 'banana', label: 'Banana' },
  { value: 'cherry', label: 'Cherry' },
  { value: 'date', label: 'Date' },
  { value: 'elderberry', label: 'Elderberry' },
];

const meta = {
  title: 'Patterns/Select',
  component: Select,
  parameters: {
    layout: 'padded',
  },
  tags: ['autodocs'],
  argTypes: {
    disabled: { control: 'boolean' },
    placeholder: { control: 'text' },
    label: { control: 'text' },
  },
} satisfies Meta<typeof Select>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: {
    id: 'fruit-select',
    options: FRUIT_OPTIONS,
    placeholder: 'Choose a fruit…',
    onChange: (value) => {
      // eslint-disable-next-line no-console
      console.log('Selected:', value);
    },
  },
};

export const WithLabel: Story = {
  args: {
    id: 'fruit-labelled',
    label: 'Fruit',
    options: FRUIT_OPTIONS,
    placeholder: 'Choose a fruit…',
    onChange: (value) => {
      // eslint-disable-next-line no-console
      console.log('Selected:', value);
    },
  },
};

export const WithValue: Story = {
  args: {
    id: 'fruit-selected',
    label: 'Fruit',
    options: FRUIT_OPTIONS,
    value: 'cherry',
    onChange: (value) => {
      // eslint-disable-next-line no-console
      console.log('Selected:', value);
    },
  },
};

export const Disabled: Story = {
  args: {
    id: 'fruit-disabled',
    label: 'Fruit',
    options: FRUIT_OPTIONS,
    placeholder: 'Unavailable',
    disabled: true,
    onChange: () => {
      /* no-op */
    },
  },
};
