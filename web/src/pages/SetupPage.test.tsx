import { render, screen } from '@testing-library/react';
import React from 'react';
import { SetupPage } from './SetupPage';

vi.mock('../features/auth/FirstRunSetupScreen/FirstRunSetupScreen', () => ({
  FirstRunSetupScreen: () =>
    React.createElement('div', { 'data-testid': 'setup-screen' }, 'Setup Screen'),
}));

describe('SetupPage', () => {
  it('renders the FirstRunSetupScreen feature', () => {
    render(<SetupPage />);
    expect(screen.getByTestId('setup-screen')).toBeInTheDocument();
  });

  it('holds the screen in the one main landmark', () => {
    render(<SetupPage />);
    expect(screen.getByRole('main')).toContainElement(screen.getByTestId('setup-screen'));
  });
});
