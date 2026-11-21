import type { DocThumbKind } from './DocThumb';

export type { DocThumbKind };

/**
 * Map a free-text Paperless document type to a `DocThumb` page shape,
 * case-insensitively, so a document shows the same thumbnail everywhere:
 *
 *   - "invoice" / "receipt"   → invoice
 *   - "statement" / "payslip" → statement
 *   - everything else         → letter
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
