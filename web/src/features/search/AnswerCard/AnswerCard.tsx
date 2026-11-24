import React from 'react';
import { AnswerSurface } from '../../../components/primitives/AnswerSurface/AnswerSurface';
import { Card } from '../../../components/primitives/Card/Card';
import { Icon } from '../../../components/primitives/Icon/Icon';
import { Stack } from '../../../components/layout/Stack/Stack';
import { Text } from '../../../components/primitives/Text/Text';
import type {
  CostSummary,
  OutcomeKind,
  SourceDocument,
  SearchStats,
} from '../../../api/types';
import { CitationMark } from '../../../components/primitives/CitationMark/CitationMark';
import { formatSummaryCostLabel } from '../trace/phaseStages';

export interface AnswerCardProps {
  /** Synthesised answer with inline `[document_id]` citation markers. */
  answer: string;
  /**
   * Ranked sources. Markers resolve by `document_id`; the source's 1-based
   * position becomes the citation index the user sees.
   */
  sources: SourceDocument[];
  /** Drives the provenance footer. */
  stats: SearchStats;
  /** Whole-query token and cost totals for the footer chip; omitted means no chip. */
  cost?: CostSummary;
  /**
   * `"answered"` (default) renders the answer with citations; `"clarify"` and
   * `"no_match"` render a retry nudge with no citations.
   */
  outcomeKind?: OutcomeKind;
  /** Called with the 1-based source index of the activated citation. */
  onCitationActivate?: (index: number) => void;
}

type TextSegment = { type: 'text'; value: string };
/** A parsed `[N]` marker; `docId` is the raw number, not yet a source index. */
type CitationSegment = { type: 'citation'; docId: number };
type Segment = TextSegment | CitationSegment;

/** Split an answer into text and `[N]` citation segments (N is a document id). */
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

/** Split an answer into plain and `**bold**` runs; unpaired markers stay text. */
function splitBold(answer: string): { bold: boolean; value: string }[] {
  // The single capture group puts every bold run at an odd index.
  return answer
    .split(/\*\*(\S(?:.*?\S)?)\*\*/)
    .map((value, i) => ({ bold: i % 2 === 1, value }));
}

/** "What to try" hints shown below the nudge message in retry states. */
const RETRY_HINT: Record<'clarify' | 'no_match', string> = {
  clarify:
    'Try including a document type, date range, or correspondent to narrow things down.',
  no_match:
    'Try rephrasing with different keywords, or remove any active filters.',
};

/**
 * The synthesised-answer card. For the clarify and no_match retry states the
 * `answer` field carries the nudge message and sources are empty.
 */
export function AnswerCard({
  answer,
  sources,
  stats,
  cost,
  outcomeKind = 'answered',
  onCitationActivate,
}: AnswerCardProps): React.ReactElement {
  if (outcomeKind === 'clarify' || outcomeKind === 'no_match') {
    const hint = RETRY_HINT[outcomeKind];
    return (
      <Card as="article" elevated>
        <Stack direction="vertical" gap={6}>
          <Stack direction="horizontal" gap={6} align="center">
            <Icon name="info" size="small" />
            <Text as="p" variant="body-emphasis" tone="primary">
              {answer}
            </Text>
          </Stack>
          <Text as="p" variant="caption" tone="secondary">
            {hint}
          </Text>
        </Stack>
      </Card>
    );
  }

  const renderCited = (text: string): React.ReactNode[] =>
    parseAnswer(text).map((segment, i) => {
      if (segment.type === 'text') {
        return <React.Fragment key={i}>{segment.value}</React.Fragment>;
      }

      // A document that didn't make the result set renders verbatim rather
      // than as a dead control.
      const sourceIndex = sources.findIndex(
        (s) => s.document_id === segment.docId,
      );
      if (sourceIndex === -1) {
        return <React.Fragment key={i}>[{segment.docId}]</React.Fragment>;
      }

      return (
        <CitationMark
          key={i}
          index={sourceIndex + 1}
          {...(onCitationActivate !== undefined ? { onActivate: onCitationActivate } : {})}
          sourceTitle={sources[sourceIndex]?.title ?? null}
        />
      );
    });

  const costLabel =
    cost !== undefined ? formatSummaryCostLabel(cost) : undefined;

  return (
    <AnswerSurface
      sourceCount={sources.length}
      latencyMs={stats.latency_ms}
      refined={stats.refined}
      {...(costLabel !== undefined ? { costLabel } : {})}
    >
      {splitBold(answer).map((run, i) =>
        run.bold ? (
          <strong key={i}>{renderCited(run.value)}</strong>
        ) : (
          <React.Fragment key={i}>{renderCited(run.value)}</React.Fragment>
        ),
      )}
    </AnswerSurface>
  );
}
