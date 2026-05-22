import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { KeysPage } from './KeysPage';

vi.mock('../features/shell/AppNavBar/AppNavBar', () => ({
  AppNavBar: () => <div data-testid="app-nav" />,
}));
vi.mock('../features/access/APIKeysScreen/APIKeysScreen', () => ({
  APIKeysScreen: () => <div data-testid="keys-screen" />,
}));

describe('KeysPage', () => {
  it('renders the app nav bar and the keys screen', () => {
    render(
      <MemoryRouter>
        <KeysPage />
      </MemoryRouter>,
    );
    expect(screen.getByTestId('app-nav')).toBeInTheDocument();
    expect(screen.getByTestId('keys-screen')).toBeInTheDocument();
  });
});
