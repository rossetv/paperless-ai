import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { SettingsPage } from './SettingsPage';

// Stub the two features so the page is tested as a composition only.
vi.mock('../features/shell/AppNavBar/AppNavBar', () => ({
  AppNavBar: () => <div data-testid="app-nav" />,
}));
vi.mock('../features/settings/SettingsScreen/SettingsScreen', () => ({
  SettingsScreen: () => <div data-testid="settings-screen" />,
}));

describe('SettingsPage', () => {
  it('renders the app nav bar and the settings screen', () => {
    render(
      <MemoryRouter>
        <SettingsPage />
      </MemoryRouter>,
    );
    expect(screen.getByTestId('app-nav')).toBeInTheDocument();
    expect(screen.getByTestId('settings-screen')).toBeInTheDocument();
  });
});
