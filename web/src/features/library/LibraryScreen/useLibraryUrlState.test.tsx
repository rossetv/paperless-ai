import React from 'react';
import { describe, it, expect } from 'vitest';
import { renderHook, render, fireEvent } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { useLibraryUrlState } from './useLibraryUrlState';

function makeWrapper(initialEntry: string) {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return <MemoryRouter initialEntries={[initialEntry]}>{children}</MemoryRouter>;
  };
}

describe('useLibraryUrlState', () => {
  it('returns the default query when no params are present', () => {
    const { result } = renderHook(() => useLibraryUrlState(), {
      wrapper: makeWrapper('/library'),
    });
    expect(result.current.query).toEqual({
      page: 1,
      page_size: 24,
      sort: 'added',
      descending: true,
      query: null,
      correspondent_id: null,
      document_type_id: null,
      tag_ids: [],
      date_from: null,
      date_to: null,
    });
    expect(result.current.view).toBe('grid');
  });

  it('parses each query parameter into the typed query', () => {
    const url =
      '/library?q=invoice&type=4&corr=2&tag=12&tag=33&from=2024-01-01&to=2024-12-31&sort=created&desc=0&page=3&view=list';
    const { result } = renderHook(() => useLibraryUrlState(), {
      wrapper: makeWrapper(url),
    });
    expect(result.current.query.query).toBe('invoice');
    expect(result.current.query.document_type_id).toBe(4);
    expect(result.current.query.correspondent_id).toBe(2);
    expect(result.current.query.tag_ids).toEqual([12, 33]);
    expect(result.current.query.date_from).toBe('2024-01-01');
    expect(result.current.query.date_to).toBe('2024-12-31');
    expect(result.current.query.sort).toBe('created');
    expect(result.current.query.descending).toBe(false);
    expect(result.current.query.page).toBe(3);
    expect(result.current.view).toBe('list');
  });

  it('ignores non-integer tag values silently', () => {
    const { result } = renderHook(() => useLibraryUrlState(), {
      wrapper: makeWrapper('/library?tag=12&tag=abc&tag=33'),
    });
    expect(result.current.query.tag_ids).toEqual([12, 33]);
  });

  it('setQuery writes a clean URL with defaults stripped', () => {
    function Probe() {
      const state = useLibraryUrlState();
      const loc = useLocation();
      return (
        <>
          <button
            onClick={() =>
              state.setQuery({
                ...state.query,
                query: 'invoice',
                tag_ids: [5],
                page: 1, // default — must be stripped
                sort: 'added', // default — must be stripped
                descending: true, // default — must be stripped
              })
            }
          >
            apply
          </button>
          <span data-testid="url">
            {loc.pathname}
            {loc.search}
          </span>
        </>
      );
    }
    const { container, getByTestId } = render(
      <MemoryRouter initialEntries={['/library']}>
        <Probe />
      </MemoryRouter>,
    );
    fireEvent.click(container.querySelector('button')!);
    expect(getByTestId('url').textContent).toBe('/library?q=invoice&tag=5');
  });

  it('setView writes view=list and strips it when set back to grid', () => {
    function Probe() {
      const { view, setView } = useLibraryUrlState();
      const loc = useLocation();
      return (
        <>
          <button data-testid="to-list" onClick={() => setView('list')}>list</button>
          <button data-testid="to-grid" onClick={() => setView('grid')}>grid</button>
          <span data-testid="url">{loc.pathname}{loc.search}</span>
          <span data-testid="view">{view}</span>
        </>
      );
    }
    const { getByTestId } = render(
      <MemoryRouter initialEntries={['/library']}>
        <Probe />
      </MemoryRouter>,
    );
    fireEvent.click(getByTestId('to-list'));
    expect(getByTestId('url').textContent).toBe('/library?view=list');
    fireEvent.click(getByTestId('to-grid'));
    expect(getByTestId('url').textContent).toBe('/library');
  });
});
