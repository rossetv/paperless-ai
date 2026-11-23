import { screen } from '@testing-library/react';

vi.mock('./App', () => ({
  default: () => {
    throw new Error('boom');
  },
}));

describe('main', () => {
  it('shows the app fallback, not the router error page, when a route throws', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    document.body.innerHTML = '<div id="root"></div>';
    await import('./main');
    expect(await screen.findByRole('heading', { name: 'Something went wrong' })).toBeInTheDocument();
    expect(screen.queryByText('Unexpected Application Error!')).not.toBeInTheDocument();
  });
});
