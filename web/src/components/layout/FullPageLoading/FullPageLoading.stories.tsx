import type { Meta, StoryObj } from '@storybook/react';
import { FullPageLoading } from './FullPageLoading';

const meta = {
  title: 'Layout/FullPageLoading',
  component: FullPageLoading,
  parameters: {
    layout: 'fullscreen',
  },
  tags: ['autodocs'],
} satisfies Meta<typeof FullPageLoading>;

export default meta;
type Story = StoryObj<typeof meta>;

/**
 * Default full-viewport loading screen shown while bootstrap queries resolve.
 * Renders a centred Spinner on a dark backdrop.
 */
export const Default: Story = {};
