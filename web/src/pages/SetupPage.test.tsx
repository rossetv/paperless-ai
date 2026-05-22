import { render, screen } from '@testing-library/react';
import { SetupPage } from './SetupPage';

describe('SetupPage', () => {
  it('renders the setup page', () => {
    render(<SetupPage />);
    expect(screen.getByTestId('setup-page')).toBeInTheDocument();
  });
});
