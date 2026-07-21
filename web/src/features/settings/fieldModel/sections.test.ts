// vitest here uses explicit imports (no globals) — matches the repo convention (e.g. cn.test.ts).
import { describe, it, expect } from 'vitest';
import { SETTINGS_SECTIONS } from './sections';

describe('born-digital OCR-skip settings', () => {
  it('exposes born-digital OCR-skip fields', () => {
    const ocr = SETTINGS_SECTIONS.find((s) => s.id === 'ocr')!;
    const ocrFields = ocr.groups.flatMap((g) => [...g.fields, ...(g.advanced ?? [])]);
    expect(ocrFields.find((f) => f.key === 'OCR_SKIP_BORN_DIGITAL')!.control.kind).toBe('toggle');
    expect(ocrFields.find((f) => f.key === 'OCR_BORN_DIGITAL_MIN_CHARS')!.control.kind).toBe(
      'number',
    );
    // master switch must be visible, not buried in an advanced fold:
    const bornGroup = ocr.groups.find((g) => g.id === 'born-digital')!;
    expect(bornGroup.fields.some((f) => f.key === 'OCR_SKIP_BORN_DIGITAL')).toBe(true);

    const automation = SETTINGS_SECTIONS.find((s) => s.id === 'automation')!;
    const tagsGroup = automation.groups.find((g) => g.id === 'tags')!;
    const tag = tagsGroup.fields.find((f) => f.key === 'OCR_BORN_DIGITAL_TAG_ID')!;
    expect(tag.control.kind).toBe('number');
  });
});
