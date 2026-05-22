import type { Meta, StoryObj } from '@storybook/react';
import { DocThumb } from './DocThumb';

const meta = {
  title: 'Primitives/DocThumb',
  component: DocThumb,
  parameters: { layout: 'centered' },
  tags: ['autodocs'],
} satisfies Meta<typeof DocThumb>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Statement: Story = { args: { kind: 'statement', matched: [3, 4] } };
export const Invoice: Story = { args: { kind: 'invoice', matched: [5, 6] } };
export const Letter: Story = { args: { kind: 'letter', matched: [] } };

export const AllKinds: StoryObj = {
  render: () => (
    <div style={{ display: 'flex', gap: 'var(--spacing-13)' }}>
      <DocThumb kind="statement" matched={[3, 4, 7]} />
      <DocThumb kind="invoice" matched={[5, 6]} />
      <DocThumb kind="letter" matched={[2]} />
    </div>
  ),
};
