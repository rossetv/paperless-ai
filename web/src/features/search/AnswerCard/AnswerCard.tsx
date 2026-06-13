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
  /** The synthesised answer text, with `[document_id]` inline citation markers
   *  pointing at concrete source documents in the results. */
  answer: string;
  /** The ranked sources — citation markers are resolved against this list by
   *  matching `document_id`; the source's 1-based position in the list
   *  becomes the user-facing citation index. */
  sources: SourceDocument[];
  /** Execution statistics — drives the provenance footer. */
  stats: SearchStats;
  /**
   * Whole-query token + cost totals — rendered as a chip in the answer
   * footer. Optional so retry-state callers (clarify/no_match) and older tests
   * need not supply it; omitted ⇒ no cost chip.
   */
  cost?: CostSummary;
  /**
   * Discriminator for the result type.
   * ``"answered"``  → normal answer + citations.
   * ``"clarify"``   → retry state: nudge message only, no citations block.
   * ``"no_match"``  → retry state: nudge message only, no citations block.
   * Defaults to ``"answered"`` so existing callers that pre-date this field
   * keep working unchanged.
   */
  outcomeKind?: OutcomeKind;
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
 * Short "what to try" hints shown below the nudge message in retry states.
 *
 * ``"clarify"``  — query was too vague; guide the user toward a more specific
 *                  phrasing before they re-submit.
 * ``"no_match"`` — retrieval failed; guide the user toward rephrasing or
 *                  broadening the query.
 */
const RETRY_HINT: Record<'clarify' | 'no_match', string> = {
  clarify:
    'Try including a document type, date range, or correspondent to narrow things down.',
  no_match:
    'Try rephrasing with different keywords, or remove any active filters.',
};

/**
 * The synthesised-answer card, restyled to the search-redesign design.
 *
 * For ``outcome_kind === "answered"`` (the default) it composes the
 * ``AnswerSurface`` primitive (eyebrow + display prose + provenance footer)
 * with inline ``CitationMark``s resolved against the sources list.
 *
 * For ``"clarify"`` and ``"no_match"`` it renders a distinct, friendly
 * **retry state**: a ``Card`` containing the nudge message (from the ``answer``
 * field) and a short "what to try" hint. No citations or sources block is
 * shown — sources are empty for retry kinds.
 *
 * Composed from: AnswerSurface, CitationMark, Card, Icon, Stack, Text.
 * No own CSS module (§12.5 — features layer is composition-only).
 * All visual values come from design tokens (§12.4).
 */
export function AnswerCard({
  answer,
  sources,
  stats,
  cost,
  outcomeKind = 'answered',
  onCitationActivate,
}: AnswerCardProps): React.ReactElement {
  // ── Retry state (clarify / no_match) ─────────────────────────────────────
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

  // ── Normal answered state ─────────────────────────────────────────────────
  const segments = parseAnswer(answer);
  const costLabel =
    cost !== undefined ? formatSummaryCostLabel(cost) : undefined;

  return (
    <AnswerSurface
      sourceCount={sources.length}
      latencyMs={stats.latency_ms}
      refined={stats.refined}
      {...(costLabel !== undefined ? { costLabel } : {})}
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
            {...(onCitationActivate !== undefined ? { onActivate: onCitationActivate } : {})}
            sourceTitle={source?.title ?? null}
          />
        );
      })}
    </AnswerSurface>
  );
}
