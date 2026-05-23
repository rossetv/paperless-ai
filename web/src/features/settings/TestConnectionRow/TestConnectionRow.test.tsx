import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { TestConnectionRow } from './TestConnectionRow';

function makeWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

function mockFetch(status: number, body: unknown): void {
  const json = JSON.stringify(body);
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok: status >= 200 && status < 300,
      status,
      headers: { get: () => null },
      text: async () => json,
      json: async () => body,
    }),
  );
}

describe('TestConnectionRow', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('renders a Run test button', () => {
    render(
      <TestConnectionRow url="http://x" token="tok" tokenIsMasked={false} />,
      { wrapper: makeWrapper() },
    );
    expect(screen.getByRole('button', { name: /run test/i })).toBeInTheDocument();
  });

  it('probes with the draft url and token on click', async () => {
    mockFetch(200, { ok: true, document_count: 14238, detail: 'ok' });
    render(
      <TestConnectionRow url="http://paperless.lan" token="real-tok" tokenIsMasked={false} />,
      { wrapper: makeWrapper() },
    );
    await userEvent.click(screen.getByRole('button', { name: /run test/i }));
    await waitFor(() => {
      const call = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
      const body = JSON.parse((call[1] as RequestInit).body as string);
      expect(body).toEqual({
        paperless_url: 'http://paperless.lan',
        paperless_token: 'real-tok',
      });
    });
  });

  it('sends an empty token when the token is masked', async () => {
    mockFetch(200, { ok: true, document_count: 1, detail: 'ok' });
    render(
      <TestConnectionRow url="http://x" token="••••mask" tokenIsMasked />,
      { wrapper: makeWrapper() },
    );
    await userEvent.click(screen.getByRole('button', { name: /run test/i }));
    await waitFor(() => {
      const call = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
      const body = JSON.parse((call[1] as RequestInit).body as string);
      expect(body.paperless_token).toBe('');
    });
  });

  it('shows a success message with the document count', async () => {
    mockFetch(200, { ok: true, document_count: 14238 });
    render(
      <TestConnectionRow url="http://x" token="tok" tokenIsMasked={false} />,
      { wrapper: makeWrapper() },
    );
    await userEvent.click(screen.getByRole('button', { name: /run test/i }));
    expect(await screen.findByText(/14,?238 documents/)).toBeInTheDocument();
  });

  it('shows the failure detail when the probe is rejected', async () => {
    mockFetch(200, { ok: false, detail: 'HTTP 401 — invalid token' });
    render(
      <TestConnectionRow url="http://x" token="bad" tokenIsMasked={false} />,
      { wrapper: makeWrapper() },
    );
    await userEvent.click(screen.getByRole('button', { name: /run test/i }));
    expect(await screen.findByText(/invalid token/i)).toBeInTheDocument();
  });

  it('shows a network-error message when the request throws', async () => {
    mockFetch(500, { detail: 'boom' });
    render(
      <TestConnectionRow url="http://x" token="tok" tokenIsMasked={false} />,
      { wrapper: makeWrapper() },
    );
    await userEvent.click(screen.getByRole('button', { name: /run test/i }));
    expect(await screen.findByText(/could not reach/i)).toBeInTheDocument();
  });
});
