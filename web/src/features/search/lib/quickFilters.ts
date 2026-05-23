/**
 * Preset quick-filter queries shared across search screens.
 *
 * These are canned query strings — not data — used as suggestion prompts.
 * IdleScreen renders them as chips; NoResultsScreen renders them as "Try
 * instead" rows. Defined once here so neither screen can drift from the
 * other (CODE_GUIDELINES §1.3 — never duplicate, always reuse).
 */
export const QUICK_FILTERS: readonly string[] = [
  'Invoices this month',
  'Recent contracts',
  'Tax 2024',
  'Bank statements',
  'Medical receipts',
  'Personal IDs',
];
