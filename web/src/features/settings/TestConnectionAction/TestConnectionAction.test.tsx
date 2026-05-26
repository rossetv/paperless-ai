import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { TestConnectionAction } from './TestConnectionAction';

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

describe('TestConnectionAction', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('renders a Run test button', () => {
    render(
      <TestConnectionAction url="http://x" token="tok" tokenIsMasked={false} />,
      { wrapper: makeWrapper() },
    );
    expect(screen.getByRole('button', { name: /run test/i })).toBeInTheDocument();
  });

  it('probes with the draft url and token on click', async () => {
    mockFetch(200, { ok: true, document_count: 14238, detail: 'ok' });
    render(
      <TestConnectionAction url="http://paperless.lan" token="real-tok" tokenIsMasked={false} />,
      { wrapper: makeWrapper() },
    );
    await userEvent.click(screen.getByRole('button', { name: /run test/i }));
    await waitFor(() => {
      const call = (fetch as ReturnType<typeof vi.fn>).mock.calls[0]!;
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
      <TestConnectionAction url="http://x" token="••••mask" tokenIsMasked />,
      { wrapper: makeWrapper() },
    );
    await userEvent.click(screen.getByRole('button', { name: /run test/i }));
    await waitFor(() => {
      const call = (fetch as ReturnType<typeof vi.fn>).mock.calls[0]!;
      const body = JSON.parse((call[1] as RequestInit).body as string);
      expect(body.paperless_token).toBe('');
    });
  });

  it('shows a success message with the document count', async () => {
    mockFetch(200, { ok: true, document_count: 14238 });
    render(
      <TestConnectionAction url="http://x" token="tok" tokenIsMasked={false} />,
      { wrapper: makeWrapper() },
    );
    await userEvent.click(screen.getByRole('button', { name: /run test/i }));
    expect(await screen.findByText(/14,?238 docs/)).toBeInTheDocument();
  });

  it('shows an error status when the probe is rejected', async () => {
    mockFetch(200, { ok: false, detail: 'HTTP 401 — invalid token' });
    render(
      <TestConnectionAction url="http://x" token="bad" tokenIsMasked={false} />,
      { wrapper: makeWrapper() },
    );
    await userEvent.click(screen.getByRole('button', { name: /run test/i }));
    // Short label visible in the conn-label span (truncated to 18ch)
    await waitFor(() => {
      expect(screen.queryByText(/untested/i)).not.toBeInTheDocument();
    });
  });

  it('shows an error status when the request throws', async () => {
    mockFetch(500, { detail: 'boom' });
    render(
      <TestConnectionAction url="http://x" token="tok" tokenIsMasked={false} />,
      { wrapper: makeWrapper() },
    );
    await userEvent.click(screen.getByRole('button', { name: /run test/i }));
    expect(await screen.findByText(/error/i)).toBeInTheDocument();
  });
});
