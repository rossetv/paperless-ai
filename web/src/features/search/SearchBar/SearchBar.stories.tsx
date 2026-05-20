import type { Meta, StoryObj } from '@storybook/react';
import { SearchBar } from './SearchBar';

const meta = {
  title: 'Features/Search/SearchBar',
  component: SearchBar,
  parameters: {
    layout: 'padded',
  },
  argTypes: {
    onSearch: { action: 'searched' },
  },
} satisfies Meta<typeof SearchBar>;

export default meta;
type Story = StoryObj<typeof meta>;

/** Default — empty search bar awaiting input. */
export const Default: Story = {
  args: {
    onSearch: () => undefined,
  },
};

/** Pre-populated with an initial query (e.g. from a URL parameter). */
export const WithInitialQuery: Story = {
  args: {
    initialQuery: 'boiler warranty certificate',
    onSearch: () => undefined,
  },
};

/** Disabled — shown while a search is in flight. */
export const Disabled: Story = {
  args: {
    disabled: true,
    initialQuery: 'searching…',
    onSearch: () => undefined,
  },
};
