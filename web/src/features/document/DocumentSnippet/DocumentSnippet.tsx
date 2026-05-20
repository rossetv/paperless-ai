import React from 'react';
import { Text } from '../../../components/primitives/Text/Text';

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
 * Renders the matched-content snippet as body text. When the snippet is empty
 * (the server had no excerpt for this document), a short accessible notice is
 * shown in place of the missing text — the component never renders a blank,
 * unparseable gap.
 *
 * Composed from: Text — typography comes from the type-scale primitive, not
 * global element CSS. No own CSS module (§12.5 — features layer is
 * composition-only).
 */
export function DocumentSnippet({ snippet }: DocumentSnippetProps): React.ReactElement {
  if (snippet.length === 0) {
    // The visible text is itself the accessible notice — no aria-label needed.
    return (
      <Text variant="body" tone="tertiary">
        No excerpt available.
      </Text>
    );
  }
  return <Text variant="body">{snippet}</Text>;
}
