import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { UsersPage } from './UsersPage';

// Stub the two features so the page is tested as a composition only.
vi.mock('../features/shell/AppNavBar/AppNavBar', () => ({
  AppNavBar: () => <div data-testid="app-nav" />,
}));
vi.mock('../features/access/UsersScreen/UsersScreen', () => ({
  UsersScreen: () => <div data-testid="users-screen" />,
}));

describe('UsersPage', () => {
  it('renders the app nav bar and the users screen', () => {
    render(
      <MemoryRouter>
        <UsersPage />
      </MemoryRouter>,
    );
    expect(screen.getByTestId('app-nav')).toBeInTheDocument();
    expect(screen.getByTestId('users-screen')).toBeInTheDocument();
  });
});
