/**
 * Tests for LoginPage.
 *
 * LoginPage is a thin host for the `LoginScreen` feature. The feature is
 * mocked so this test only verifies the page renders it.
 */

import { render, screen } from '@testing-library/react';
import React from 'react';
import { LoginPage } from './LoginPage';

vi.mock('../features/auth/LoginScreen/LoginScreen', () => ({
  LoginScreen: () =>
    React.createElement('div', { 'data-testid': 'login-screen' }, 'Login Screen'),
}));

describe('LoginPage', () => {
  it('renders the LoginScreen feature', () => {
    render(<LoginPage />);
    expect(screen.getByTestId('login-screen')).toBeInTheDocument();
  });
});
