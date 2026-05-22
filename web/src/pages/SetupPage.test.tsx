/**
 * Tests for SetupPage.
 *
 * SetupPage is a thin host for the `FirstRunSetupScreen` feature, which is
 * mocked here so the test only verifies the page renders it.
 */

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
});
