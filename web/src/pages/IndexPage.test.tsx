import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { IndexPage } from './IndexPage';

// Stub the two features so the page is tested as a composition only.
vi.mock('../features/shell/AppNavBar/AppNavBar', () => ({
  AppNavBar: () => <nav aria-label="Main" data-testid="app-nav" />,
}));
vi.mock('../features/index/IndexScreen/IndexScreen', () => ({
  IndexScreen: () => <div data-testid="index-screen" />,
}));

describe('IndexPage', () => {
  it('renders the app nav bar and the index screen', () => {
    render(
      <MemoryRouter>
        <IndexPage />
      </MemoryRouter>,
    );
    expect(screen.getByTestId('app-nav')).toBeInTheDocument();
    expect(screen.getByTestId('index-screen')).toBeInTheDocument();
  });

  it('keeps the nav bar outside the one main landmark that holds the screen', () => {
    render(
      <MemoryRouter>
        <IndexPage />
      </MemoryRouter>,
    );
    const main = screen.getByRole('main');
    expect(main).toContainElement(screen.getByTestId('index-screen'));
    expect(main).not.toContainElement(screen.getByTestId('app-nav'));
  });
});
