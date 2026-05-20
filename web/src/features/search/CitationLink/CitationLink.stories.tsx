import type { Meta, StoryObj } from '@storybook/react';
import { CitationLink } from './CitationLink';

const meta = {
  title: 'Features/Search/CitationLink',
  component: CitationLink,
  parameters: {
    layout: 'centered',
  },
  argTypes: {
    onActivate: { action: 'activated' },
  },
} satisfies Meta<typeof CitationLink>;

export default meta;
type Story = StoryObj<typeof meta>;

/** First citation marker. */
export const First: Story = {
  args: {
    index: 1,
    onActivate: () => undefined,
  },
};

/** Higher citation index. */
export const Higher: Story = {
  args: {
    index: 7,
    onActivate: () => undefined,
  },
};

/** Multiple citation links inline — typical usage inside an answer paragraph. */
export const InlineGroup: StoryObj = {
  render: () => (
    <p>
      The boiler was installed in 2021{' '}
      <CitationLink index={1} onActivate={() => undefined} />{' '}
      and the warranty covers five years{' '}
      <CitationLink index={2} onActivate={() => undefined} />.
    </p>
  ),
};
