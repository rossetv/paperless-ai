import React from 'react';
import { AnswerSurface } from '../../../components/primitives/AnswerSurface/AnswerSurface';
import type { SourceDocument, SearchStats } from '../../../api/types';
import { CitationLink } from '../CitationLink/CitationLink';

export interface AnswerCardProps {
  /** The synthesised answer text, with `[n]` inline citation markers. */
  answer: string;
  /** The ranked sources — used to validate citation indices. */
  sources: SourceDocument[];
  /** Execution statistics — drives the provenance footer. */
  stats: SearchStats;
  /** Called with a 1-based index when a citation marker is activated. */
  onCitationActivate?: (index: number) => void;
}

type TextSegment = { type: 'text'; value: string };
type CitationSegment = { type: 'citation'; index: number };
type Segment = TextSegment | CitationSegment;

/**
 * Split an answer string into plain-text and citation segments.
 *
 * `[n]` runs become citation segments; everything else is plain text. The
 * caller renders citation segments as `CitationLink`s and text verbatim.
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
    segments.push({ type: 'citation', index: parseInt(match[1] ?? '0', 10) });
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
 * citation markers; in-range markers render as `CitationLink`s, out-of-range
 * markers render verbatim so a bad citation never becomes a dead control.
 *
 * Composed from: AnswerSurface, CitationLink. No own CSS module (§12.5 —
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

        const inRange =
          segment.index >= 1 && segment.index <= sources.length;
        if (!inRange) {
          return <React.Fragment key={i}>[{segment.index}]</React.Fragment>;
        }

        const source = sources[segment.index - 1];
        return (
          <CitationLink
            key={i}
            index={segment.index}
            onActivate={handleCitationActivate}
            sourceTitle={source?.title ?? null}
          />
        );
      })}
    </AnswerSurface>
  );
}
