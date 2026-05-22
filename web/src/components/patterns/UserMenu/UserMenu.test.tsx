import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { UserMenu } from './UserMenu';

describe('UserMenu', () => {
  it('renders the avatar trigger with the initials', () => {
    render(<UserMenu initials="AM" displayName="Alex Morgan" email="alex@home.lan" onSignOut={vi.fn()} />);
    expect(screen.getByText('AM')).toBeInTheDocument();
  });

  it('the trigger is a button labelled for accessibility', () => {
    render(<UserMenu initials="AM" displayName="Alex Morgan" email="alex@home.lan" onSignOut={vi.fn()} />);
    expect(screen.getByRole('button', { name: /account menu/i })).toBeInTheDocument();
  });

  it('the dropdown is closed initially', () => {
    render(<UserMenu initials="AM" displayName="Alex Morgan" email="alex@home.lan" onSignOut={vi.fn()} />);
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
  });

  it('opens the dropdown when the trigger is clicked', async () => {
    render(<UserMenu initials="AM" displayName="Alex Morgan" email="alex@home.lan" onSignOut={vi.fn()} />);
    await userEvent.click(screen.getByRole('button', { name: /account menu/i }));
    expect(screen.getByRole('menu')).toBeInTheDocument();
  });

  it('sets aria-expanded on the trigger to reflect open state', async () => {
    render(<UserMenu initials="AM" displayName="Alex Morgan" email="alex@home.lan" onSignOut={vi.fn()} />);
    const trigger = screen.getByRole('button', { name: /account menu/i });
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
    await userEvent.click(trigger);
    expect(trigger).toHaveAttribute('aria-expanded', 'true');
  });

  it('shows the display name and email in the dropdown header', async () => {
    render(<UserMenu initials="AM" displayName="Alex Morgan" email="alex@home.lan" onSignOut={vi.fn()} />);
    await userEvent.click(screen.getByRole('button', { name: /account menu/i }));
    expect(screen.getByText('Alex Morgan')).toBeInTheDocument();
    expect(screen.getByText('alex@home.lan')).toBeInTheDocument();
  });

  it('falls back to the username when displayName is null', async () => {
    render(<UserMenu initials="AM" displayName={null} username="alex.morgan" email={null} onSignOut={vi.fn()} />);
    await userEvent.click(screen.getByRole('button', { name: /account menu/i }));
    expect(screen.getByText('alex.morgan')).toBeInTheDocument();
  });

  it('calls onSignOut when the Sign out item is chosen', async () => {
    const onSignOut = vi.fn();
    render(<UserMenu initials="AM" displayName="Alex Morgan" email="alex@home.lan" onSignOut={onSignOut} />);
    await userEvent.click(screen.getByRole('button', { name: /account menu/i }));
    await userEvent.click(screen.getByRole('menuitem', { name: /sign out/i }));
    expect(onSignOut).toHaveBeenCalledTimes(1);
  });

  it('closes the dropdown after Sign out is chosen', async () => {
    render(<UserMenu initials="AM" displayName="Alex Morgan" email="alex@home.lan" onSignOut={vi.fn()} />);
    await userEvent.click(screen.getByRole('button', { name: /account menu/i }));
    await userEvent.click(screen.getByRole('menuitem', { name: /sign out/i }));
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
  });

  it('closes the dropdown on Escape', async () => {
    render(<UserMenu initials="AM" displayName="Alex Morgan" email="alex@home.lan" onSignOut={vi.fn()} />);
    await userEvent.click(screen.getByRole('button', { name: /account menu/i }));
    expect(screen.getByRole('menu')).toBeInTheDocument();
    await userEvent.keyboard('{Escape}');
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
  });

  it('closes the dropdown on an outside click', async () => {
    render(
      <div>
        <UserMenu initials="AM" displayName="Alex Morgan" email="alex@home.lan" onSignOut={vi.fn()} />
        <button type="button">outside</button>
      </div>,
    );
    await userEvent.click(screen.getByRole('button', { name: /account menu/i }));
    expect(screen.getByRole('menu')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'outside' }));
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
  });
});
