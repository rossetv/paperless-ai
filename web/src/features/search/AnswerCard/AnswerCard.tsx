import React from 'react';
import { AnswerSurface } from '../../../components/primitives/AnswerSurface/AnswerSurface';
import type { SourceDocument, SearchStats } from '../../../api/types';
import { CitationMark } from '../../../components/primitives/CitationMark/CitationMark';

export interface AnswerCardProps {
  /** The synthesised answer text, with `[document_id]` inline citation markers
   *  pointing at concrete source documents in the results. */
  answer: string;
  /** The ranked sources — citation markers are resolved against this list by
   *  matching `document_id`; the source's 1-based position in the list
   *  becomes the user-facing citation index. */
  sources: SourceDocument[];
  /** Execution statistics — drives the provenance footer. */
  stats: SearchStats;
  /** Called with a 1-based source index when a citation marker is activated. */
  onCitationActivate?: (index: number) => void;
}

type TextSegment = { type: 'text'; value: string };
/** A parsed `[N]` marker — `docId` is the raw number from the answer text;
 *  callers resolve it to a 1-based source index against the `sources` array. */
type CitationSegment = { type: 'citation'; docId: number };
type Segment = TextSegment | CitationSegment;

/**
 * Split an answer string into plain-text and citation segments.
 *
 * `[N]` runs become citation segments carrying the raw N (a document id, as
 * emitted by the synthesiser prompt); everything else is plain text. The
 * caller resolves each citation against the sources list — when an id has a
 * matching source the marker renders as a `CitationMark`, otherwise it is
 * shown verbatim so a stale id never becomes a dead control.
 */
function parseAnswer(answer: string): Segment[] {
  const segments: Segment[] = [];
  const pattern = /\[(\d+)\]/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(answer)) !== null) {
    if (match.index > lastIndex) {
      segments.push({
        type: 'text',
        value: answer.slice(lastIndex, match.index),
      });
    }
    segments.push({ type: 'citation', docId: parseInt(match[1] ?? '0', 10) });
    lastIndex = pattern.lastIndex;
  }

  if (lastIndex < answer.length) {
    segments.push({ type: 'text', value: answer.slice(lastIndex) });
  }

  return segments;
}

/**
 * The synthesised-answer card, restyled to the search-redesign design.
 *
 * Composes the `AnswerSurface` primitive (the eyebrow + display-prose +
 * provenance footer). The answer text is parsed into plain runs and `[n]`
 * citation markers; in-range markers render as `CitationMark`s, out-of-range
 * markers render verbatim so a bad citation never becomes a dead control.
 *
 * Composed from: AnswerSurface, CitationMark. No own CSS module (§12.5 —
 * features layer is composition-only).
 */
export function AnswerCard({
  answer,
  sources,
  stats,
  onCitationActivate,
}: AnswerCardProps): React.ReactElement {
  const segments = parseAnswer(answer);

  function handleCitationActivate(index: number): void {
    onCitationActivate?.(index);
  }

  return (
    <AnswerSurface
      sourceCount={sources.length}
      latencyMs={stats.latency_ms}
      refined={stats.refined}
    >
      {segments.map((segment, i) => {
        if (segment.type === 'text') {
          return <React.Fragment key={i}>{segment.value}</React.Fragment>;
        }

        // Resolve the raw `[N]` document id to its 1-based position in the
        // sources list. A reference to a document that didn't make the result
        // set renders verbatim — never a dead control.
        const sourceIndex = sources.findIndex(
          (s) => s.document_id === segment.docId,
        );
        if (sourceIndex === -1) {
          return <React.Fragment key={i}>[{segment.docId}]</React.Fragment>;
        }

        const oneBasedIndex = sourceIndex + 1;
        const source = sources[sourceIndex];
        return (
          <CitationMark
            key={i}
            index={oneBasedIndex}
            onActivate={handleCitationActivate}
            sourceTitle={source?.title ?? null}
          />
        );
      })}
    </AnswerSurface>
  );
}
