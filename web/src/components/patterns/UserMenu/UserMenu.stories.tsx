import type { Meta, StoryObj } from '@storybook/react';
import { UserMenu } from './UserMenu';

const meta = {
  title: 'Patterns/UserMenu',
  component: UserMenu,
  parameters: { layout: 'centered' },
  tags: ['autodocs'],
  args: {
    initials: 'AM',
    displayName: 'Alex Morgan',
    email: 'alex@home.lan',
    onSignOut: () => undefined,
  },
} satisfies Meta<typeof UserMenu>;

export default meta;
type Story = StoryObj<typeof meta>;

/** Default — collapsed avatar trigger. Click to open the menu. */
export const Default: Story = {};

/** No display name — the username is used as the header label. */
export const UsernameFallback: Story = {
  args: { displayName: null, username: 'alex.morgan', email: null },
};

/** A coloured avatar (per-user colour). */
export const ColouredAvatar: Story = {
  args: { initials: 'PK', avatarColour: '#ff3b30', displayName: 'Pat Kim', email: 'pat@home.lan' },
};

/** On the dark glass NavBar surface. */
export const OnDark: Story = {
  decorators: [
    (Story) => (
      <div style={{ background: 'var(--colour-nav-bg)', padding: 'var(--spacing-14)' }}>
        <Story />
      </div>
    ),
  ],
};
