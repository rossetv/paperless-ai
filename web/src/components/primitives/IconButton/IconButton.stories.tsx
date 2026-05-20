import type { Meta, StoryObj } from '@storybook/react';
import { IconButton } from './IconButton';

/** Minimal inline SVG icons for catalogue demonstration. */
function SearchIcon(): React.ReactElement {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <circle cx="6.5" cy="6.5" r="5" stroke="currentColor" strokeWidth="1.5" />
      <path d="M10 10L14 14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

function CloseIcon(): React.ReactElement {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path d="M3 3L13 13M13 3L3 13" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

const meta = {
  title: 'Primitives/IconButton',
  component: IconButton,
  parameters: {
    layout: 'centered',
  },
  tags: ['autodocs'],
  argTypes: {
    disabled: { control: 'boolean' },
    label: { control: 'text' },
  },
} satisfies Meta<typeof IconButton>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Search: Story = {
  args: {
    label: 'Search',
    children: <SearchIcon />,
  },
};

export const Close: Story = {
  args: {
    label: 'Close',
    children: <CloseIcon />,
  },
};

export const Disabled: Story = {
  args: {
    label: 'Search (disabled)',
    disabled: true,
    children: <SearchIcon />,
  },
};

export const AllVariants: Story = {
  render: () => (
    <div style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
      <IconButton label="Search">
        <SearchIcon />
      </IconButton>
      <IconButton label="Close">
        <CloseIcon />
      </IconButton>
      <IconButton label="Disabled" disabled>
        <SearchIcon />
      </IconButton>
    </div>
  ),
};
