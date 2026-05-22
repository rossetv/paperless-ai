import type { Meta, StoryObj } from '@storybook/react';
import { CitationMark } from './CitationMark';

const meta = {
  title: 'Primitives/CitationMark',
  component: CitationMark,
  parameters: { layout: 'centered' },
  tags: ['autodocs'],
  args: { onActivate: (index: number) => console.log('citation', index) },
} satisfies Meta<typeof CitationMark>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = { args: { index: 1 } };

export const InProse: StoryObj = {
  render: () => (
    <p style={{ fontFamily: 'var(--font-display)', fontSize: '1.25rem' }}>
      You paid £1,847.32 across twelve direct debits
      <CitationMark index={1} onActivate={() => {}} />
      <CitationMark index={2} onActivate={() => {}} /> last year.
    </p>
  ),
};
