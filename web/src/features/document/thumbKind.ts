import type { DocThumbKind } from '../../components/primitives/DocThumb/DocThumb';

/**
 * Map a free-text Paperless document type to one of `DocThumb`'s three page
 * shapes, case-insensitively.
 *
 * The single source of truth shared by `LibraryCard` and `SourceCard` so the
 * same document shows the same thumbnail shape in the library and in search
 * results. Previously each component carried its own mapping and they diverged
 * — a receipt rendered as an invoice in search but a letter in the library
 * (CODE_GUIDELINES §1.9).
 *
 *   - "invoice" / "receipt"   → invoice
 *   - "statement" / "payslip" → statement
 *   - everything else         → letter
 *
 * Tier: features/document (a leaf domain helper). Allowed deps: components/.
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
