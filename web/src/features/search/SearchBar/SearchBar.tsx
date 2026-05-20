import React from 'react';
import { SearchField } from '../../../components/patterns/SearchField/SearchField';

export interface SearchBarProps {
  /**
   * Called with the trimmed query string when the user submits.
   * Fires on Enter keypress and on the submit button click.
   * Not called for empty queries.
   */
  onSearch: (query: string) => void;
  /**
   * Optional initial value for the query field.
   * Allows the parent to pre-populate the search bar (e.g. from a URL param).
   */
  initialQuery?: string;
  /** Whether the search bar is non-interactive (e.g. during a pending search). */
  disabled?: boolean;
}

/**
 * Domain search bar — a thin composable wrapper around the SearchField pattern.
 *
 * Owns the uncontrolled input state and exposes a simple onSearch(query) API
 * to the parent. The parent is responsible for executing the search and
 * managing the search results state.
 *
 * Keeping this a controlled, composable piece (rather than owning the query
 * execution) means SearchPage can wire it to useSearch without coupling.
 *
 * Composed from: SearchField.
 * No own CSS module (§12.5 — features layer is composition-only).
 */
export function SearchBar({
  onSearch,
  initialQuery = '',
  disabled = false,
}: SearchBarProps): React.ReactElement {
  const [query, setQuery] = React.useState(initialQuery);

  function handleChange(event: React.ChangeEvent<HTMLInputElement>): void {
    setQuery(event.target.value);
  }

  function handleSubmit(submitted: string): void {
    onSearch(submitted.trim());
  }

  return (
    <SearchField
      id="main-search"
      placeholder="Search your documents…"
      value={query}
      disabled={disabled}
      onChange={handleChange}
      onSubmit={handleSubmit}
    />
  );
}
