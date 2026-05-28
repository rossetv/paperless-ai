import React from 'react';
import { describe, it, expect } from 'vitest';
import { render, fireEvent } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { useSearchUrlState } from './useSearchUrlState';

describe('useSearchUrlState', () => {
  it('parses q and the filter params from the URL', () => {
    function Probe() {
      const { query, filters } = useSearchUrlState();
      return (
        <div data-testid="state">
          {JSON.stringify({ query, filters })}
        </div>
      );
    }
    const { getByTestId } = render(
      <MemoryRouter initialEntries={['/?q=invoice&tag=5&tag=8&type=2&corr=3&from=2024-01-01&to=2024-12-31']}>
        <Probe />
      </MemoryRouter>,
    );
    const parsed = JSON.parse(getByTestId('state').textContent!);
    expect(parsed.query).toBe('invoice');
    expect(parsed.filters.tag_ids).toEqual([5, 8]);
    expect(parsed.filters.document_type_id).toBe(2);
    expect(parsed.filters.correspondent_id).toBe(3);
    expect(parsed.filters.date_from).toBe('2024-01-01');
    expect(parsed.filters.date_to).toBe('2024-12-31');
  });

  it('returns an empty query and empty filters on /', () => {
    function Probe() {
      const { query, filters } = useSearchUrlState();
      return <div data-testid="state">{JSON.stringify({ query, filters })}</div>;
    }
    const { getByTestId } = render(
      <MemoryRouter initialEntries={['/']}>
        <Probe />
      </MemoryRouter>,
    );
    const parsed = JSON.parse(getByTestId('state').textContent!);
    expect(parsed.query).toBe('');
    expect(parsed.filters).toEqual({
      tag_ids: [],
      correspondent_id: null,
      document_type_id: null,
      date_from: null,
      date_to: null,
    });
  });

  it('setQuery + setFilters write a clean URL', () => {
    function Probe() {
      const { setQuery, setFilters } = useSearchUrlState();
      const loc = useLocation();
      return (
        <>
          <button data-testid="q" onClick={() => setQuery('invoice')}>q</button>
          <button
            data-testid="f"
            onClick={() =>
              setFilters({
                tag_ids: [5],
                correspondent_id: null,
                document_type_id: null,
                date_from: null,
                date_to: null,
              })
            }
          >
            f
          </button>
          <span data-testid="url">{loc.pathname}{loc.search}</span>
        </>
      );
    }
    const { getByTestId } = render(
      <MemoryRouter initialEntries={['/']}>
        <Probe />
      </MemoryRouter>,
    );
    fireEvent.click(getByTestId('q'));
    expect(getByTestId('url').textContent).toBe('/?q=invoice');
    fireEvent.click(getByTestId('f'));
    // Setting filters preserves the existing q.
    expect(getByTestId('url').textContent).toBe('/?q=invoice&tag=5');
  });
});
