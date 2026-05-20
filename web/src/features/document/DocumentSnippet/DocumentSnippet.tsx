import React from 'react';
import { Stack } from '../../../components/layout/Stack/Stack';

export interface DocumentSnippetProps {
  /**
   * The matched-content excerpt from the search result.
   * May be an empty string when no snippet is available for this document.
   */
  snippet: string;
}

/**
 * Readable text excerpt from a search result document.
 *
 * Renders the matched-content snippet as a paragraph. When the snippet is
 * empty (the server had no excerpt for this document), a short accessible
 * notice is shown in place of the missing text — the component never renders
 * a blank, unparseable gap.
 *
 * Composed from: Stack.
 * No own CSS module (§12.5 — features layer is composition-only).
 */
export function DocumentSnippet({ snippet }: DocumentSnippetProps): React.ReactElement {
  return (
    <Stack direction="vertical">
      {snippet.length > 0 ? (
        <p>{snippet}</p>
      ) : (
        <p aria-label="No excerpt available">No excerpt available.</p>
      )}
    </Stack>
  );
}
