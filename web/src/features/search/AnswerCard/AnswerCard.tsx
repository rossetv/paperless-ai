import React from 'react';
import { Card } from '../../../components/primitives/Card/Card';
import { Stack } from '../../../components/layout/Stack/Stack';
import type { SourceDocument } from '../../../api/types';
import { CitationLink } from '../CitationLink/CitationLink';

export interface AnswerCardProps {
  answer: string;
  sources: SourceDocument[];
  onCitationActivate?: (index: number) => void;
}

type TextSegment = { type: 'text'; value: string };
type CitationSegment = { type: 'citation'; index: number };
type Segment = TextSegment | CitationSegment;

function parseAnswer(answer: string): Segment[] {
  const segments: Segment[] = [];
  const pattern = /\[(\d+)\]/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(answer)) !== null) {
    if (match.index > lastIndex) {
      segments.push({ type: 'text', value: answer.slice(lastIndex, match.index) });
    }
    // match[1] is the capture group for \d+ — always defined when the regex matches
    segments.push({ type: 'citation', index: parseInt(match[1] ?? '0', 10) });
    lastIndex = pattern.lastIndex;
  }

  if (lastIndex < answer.length) {
    segments.push({ type: 'text', value: answer.slice(lastIndex) });
  }

  return segments;
}

export function AnswerCard({
  answer,
  sources,
  onCitationActivate,
}: AnswerCardProps): React.ReactElement {
  const segments = parseAnswer(answer);

  function handleCitationActivate(index: number): void {
    onCitationActivate?.(index);
  }

  return (
    <Card as="article" elevated>
      <Stack direction="vertical" gap={6}>
        <p>
          {segments.map((segment, i) => {
            if (segment.type === 'text') {
              return <React.Fragment key={i}>{segment.value}</React.Fragment>;
            }

            const exists = segment.index >= 1 && segment.index <= sources.length;
            if (!exists) {
              return <React.Fragment key={i}>[{segment.index}]</React.Fragment>;
            }

            return (
              <CitationLink
                key={i}
                index={segment.index}
                onActivate={handleCitationActivate}
              />
            );
          })}
        </p>
      </Stack>
    </Card>
  );
}
