import React from 'react';
import { SnippetText } from '../../../components/primitives/SnippetText/SnippetText';

export interface DocumentSnippetProps {
  /**
   * The matched-content excerpt from the search result. `**phrase**` runs are
   * rendered as accent highlights. May be an empty string when no snippet is
   * available for this document.
   */
  snippet: string;
}

/**
 * Readable matched-content excerpt from a search result document.
 *
 * Delegates rendering to the `SnippetText` primitive, which highlights
 * `**bold**` runs and shows a "no excerpt" notice for an empty snippet — so a
 * search result and a bare document render their snippet identically.
 *
 * Composed from: SnippetText. No own CSS module (§12.5 — features layer is
 * composition-only).
 */
export function DocumentSnippet({
  snippet,
}: DocumentSnippetProps): React.ReactElement {
  return <SnippetText text={snippet} />;
}
