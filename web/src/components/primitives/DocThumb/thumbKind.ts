import type { DocThumbKind } from './DocThumb';

export type { DocThumbKind };

/**
 * Map a free-text Paperless document type to one of `DocThumb`'s three page
 * shapes, case-insensitively.
 *
 * The single source of truth shared by `LibraryCard`, `SourceCard`, and any
 * other consumer, so the same document always shows the same thumbnail shape.
 * Previously sat in `features/document`; promoted here (beside `DocThumb`)
 * because it is used by three unrelated feature domains — library, search, and
 * document — and shared helpers must live in `components/` not `features/`
 * (CODE_GUIDELINES §12.3, DD-6).
 *
 *   - "invoice" / "receipt"   → invoice
 *   - "statement" / "payslip" → statement
 *   - everything else         → letter
 *
 * Tier: components/primitives (CODE_GUIDELINES §12.3). Allowed deps: none beyond
 * the sibling DocThumb type.
 */
export function thumbKindForDocumentType(documentType: string | null): DocThumbKind {
  const text = (documentType ?? '').toLowerCase();
  if (text.includes('invoice') || text.includes('receipt')) {
    return 'invoice';
  }
  if (text.includes('statement') || text.includes('payslip')) {
    return 'statement';
  }
  return 'letter';
}
