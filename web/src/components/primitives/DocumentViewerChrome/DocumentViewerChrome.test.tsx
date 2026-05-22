import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DocumentViewerChrome } from './DocumentViewerChrome';

function renderChrome(overrides = {}) {
  return render(
    <DocumentViewerChrome
      title="Annual energy statement"
      paperlessUrl="https://paperless.example.com/documents/9823/"
      onClose={() => {}}
      {...overrides}
    >
      <div data-testid="page-area">page</div>
    </DocumentViewerChrome>,
  );
}

describe('DocumentViewerChrome', () => {
  it('renders the document title in the breadcrumb', () => {
    renderChrome();
    expect(screen.getByText('Annual energy statement')).toBeInTheDocument();
  });

  it('renders the page-area children', () => {
    renderChrome();
    expect(screen.getByTestId('page-area')).toBeInTheDocument();
  });

  it('renders a close control with an accessible name', () => {
    renderChrome();
    expect(
      screen.getByRole('button', { name: /close/i }),
    ).toBeInTheDocument();
  });

  it('fires onClose when the close control is clicked', async () => {
    const onClose = vi.fn();
    renderChrome({ onClose });
    await userEvent.click(screen.getByRole('button', { name: /close/i }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('renders an "Open in Paperless" external link', () => {
    renderChrome();
    const link = screen.getByRole('link', { name: /open in paperless/i });
    expect(link).toHaveAttribute(
      'href',
      'https://paperless.example.com/documents/9823/',
    );
    expect(link).toHaveAttribute('target', '_blank');
  });

  it('renders a Download link pointing at the supplied url', () => {
    renderChrome({ downloadUrl: '/api/documents/9823/pdf' });
    const link = screen.getByRole('link', { name: /download/i });
    expect(link).toHaveAttribute('href', '/api/documents/9823/pdf');
  });

  it('merges a custom className', () => {
    const { container } = renderChrome({ className: 'extra' });
    expect((container.firstChild as Element).className).toContain('extra');
  });
});
