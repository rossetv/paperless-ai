import { describe, it, expect } from 'vitest';
import {
  SETTINGS_SECTIONS,
  allFieldKeys,
  fieldByKey,
  parseValue,
  serialiseValue,
} from './fieldModel';

describe('settings field model', () => {
  it('defines exactly seven sections', () => {
    expect(SETTINGS_SECTIONS).toHaveLength(7);
  });

  it('uses the seven expected section anchor ids in pipeline order', () => {
    expect(SETTINGS_SECTIONS.map((s) => s.id)).toEqual([
      'connections',
      'ocr',
      'classification',
      'indexing',
      'search',
      'automation',
      'logging',
    ]);
  });

  it('gives every section a stable anchor id and a title', () => {
    for (const section of SETTINGS_SECTIONS) {
      expect(section.id).toMatch(/^[a-z]+(-[a-z]+)*$/);
      expect(section.title.length).toBeGreaterThan(0);
      expect(section.groups.length).toBeGreaterThan(0);
    }
  });

  it('every group has a non-empty id, title, and at least one field', () => {
    for (const section of SETTINGS_SECTIONS) {
      for (const group of section.groups) {
        expect(group.id.length).toBeGreaterThan(0);
        expect(group.title.length).toBeGreaterThan(0);
        expect(group.fields.length).toBeGreaterThan(0);
      }
    }
  });

  it('never repeats a config key across the whole model', () => {
    const keys = allFieldKeys();
    expect(new Set(keys).size).toBe(keys.length);
  });

  it('gives every field a non-empty label and a control kind', () => {
    for (const section of SETTINGS_SECTIONS) {
      for (const group of section.groups) {
        const allFields = [...group.fields, ...(group.advanced ?? [])];
        for (const field of allFields) {
          expect(field.label.length).toBeGreaterThan(0);
          expect(field.control.kind).toBeTruthy();
        }
      }
    }
  });

  it('gives every number field a finite minimum', () => {
    for (const section of SETTINGS_SECTIONS) {
      for (const group of section.groups) {
        const allFields = [...group.fields, ...(group.advanced ?? [])];
        for (const field of allFields) {
          if (field.control.kind === 'number') {
            expect(Number.isFinite(field.control.min)).toBe(true);
          }
        }
      }
    }
  });

  it('marks the two known secret keys as secret', () => {
    const secret = allFieldKeys().filter((k) => {
      for (const section of SETTINGS_SECTIONS) {
        for (const group of section.groups) {
          const allFields = [...group.fields, ...(group.advanced ?? [])];
          const f = allFields.find((field) => field.key === k);
          if (f) return f.secret === true;
        }
      }
      return false;
    });
    expect(secret).toEqual(
      expect.arrayContaining(['PAPERLESS_TOKEN', 'OPENAI_API_KEY']),
    );
  });

  it('parses a wire string to the type the control needs', () => {
    const numberField = fieldByKey('SEARCH_TOP_K')!;
    expect(parseValue(numberField, '10')).toBe(10);
    const toggleField = fieldByKey('OCR_INCLUDE_PAGE_MODELS')!;
    expect(parseValue(toggleField, 'true')).toBe(true);
    expect(parseValue(toggleField, 'false')).toBe(false);
    const listField = fieldByKey('OCR_MODELS')!;
    expect(parseValue(listField, 'a, b ,c')).toEqual(['a', 'b', 'c']);
    const textField = fieldByKey('PAPERLESS_URL')!;
    expect(parseValue(textField, 'http://x')).toBe('http://x');
  });

  it('parses a null wire value to the control empty value', () => {
    expect(parseValue(fieldByKey('SEARCH_TOP_K')!, null)).toBe(0);
    expect(parseValue(fieldByKey('OCR_MODELS')!, null)).toEqual([]);
    expect(parseValue(fieldByKey('PAPERLESS_URL')!, null)).toBe('');
  });

  it('serialises a typed value back to a wire string', () => {
    expect(serialiseValue(25)).toBe('25');
    expect(serialiseValue(true)).toBe('true');
    expect(serialiseValue(false)).toBe('false');
    expect(serialiseValue(['a', 'b'])).toBe('a, b');
    expect(serialiseValue('http://x')).toBe('http://x');
  });

  it('places PAPERLESS_URL in the connections/paperless group', () => {
    const connections = SETTINGS_SECTIONS.find((s) => s.id === 'connections')!;
    const paperless = connections.groups.find((g) => g.id === 'paperless')!;
    expect(paperless.fields.map((f) => f.key)).toContain('PAPERLESS_URL');
  });

  it('structures connections into provider/paperless/openai/ollama groups', () => {
    const connections = SETTINGS_SECTIONS.find((s) => s.id === 'connections')!;
    const groupIds = connections.groups.map((g) => g.id);
    expect(groupIds).toEqual(['provider', 'paperless', 'openai', 'ollama']);
  });

  it('fieldByKey resolves a key nested inside any group', () => {
    expect(fieldByKey('EMBEDDING_MODEL')).toBeDefined();
    expect(fieldByKey('EMBEDDING_MODEL')?.key).toBe('EMBEDDING_MODEL');
    expect(fieldByKey('ERROR_TAG_ID')).toBeDefined();
    expect(fieldByKey('__unknown__')).toBeUndefined();
  });

  // ── New-model specific assertions ─────────────────────────────────────────

  it('allFieldKeys contains OCR_MODELS and CLASSIFY_MODELS', () => {
    const keys = allFieldKeys();
    expect(keys).toContain('OCR_MODELS');
    expect(keys).toContain('CLASSIFY_MODELS');
  });

  it('allFieldKeys contains SEARCH_PLANNER_REASONING_EFFORT as a reasoning sub-key', () => {
    expect(allFieldKeys()).toContain('SEARCH_PLANNER_REASONING_EFFORT');
  });

  it('allFieldKeys contains an advanced key (OCR_REFUSAL_MARKERS)', () => {
    expect(allFieldKeys()).toContain('OCR_REFUSAL_MARKERS');
  });

  it('allFieldKeys does NOT contain AI_MODELS (replaced by OCR_MODELS/CLASSIFY_MODELS)', () => {
    expect(allFieldKeys()).not.toContain('AI_MODELS');
  });

  it('allFieldKeys does NOT contain a never-surfaced key', () => {
    expect(allFieldKeys()).not.toContain('SEARCH_CACHE_TTL_SECONDS');
  });

  it('fieldByKey resolves SEARCH_PLANNER_REASONING_EFFORT (reasoning sub-key) as defined', () => {
    expect(fieldByKey('SEARCH_PLANNER_REASONING_EFFORT')).toBeDefined();
  });

  it('fieldByKey also resolves SEARCH_ANSWER_REASONING_EFFORT and SEARCH_JUDGE_REASONING_EFFORT', () => {
    expect(fieldByKey('SEARCH_ANSWER_REASONING_EFFORT')).toBeDefined();
    expect(fieldByKey('SEARCH_JUDGE_REASONING_EFFORT')).toBeDefined();
  });

  it('allFieldKeys includes no duplicates even with advanced/reasoningKey logic applied', () => {
    const keys = allFieldKeys();
    expect(new Set(keys).size).toBe(keys.length);
  });

  it('allFieldKeys still returns all group.fields keys', () => {
    const expected = SETTINGS_SECTIONS.flatMap((s) =>
      s.groups.flatMap((g) => g.fields.map((f) => f.key)),
    );
    const result = allFieldKeys();
    for (const k of expected) {
      expect(result).toContain(k);
    }
  });

  it('fieldByKey returns undefined for an unknown key and does not throw', () => {
    expect(fieldByKey('__nonexistent_key__')).toBeUndefined();
  });

  it('advanced groups are present in the new model', () => {
    // At least one group must have an advanced array.
    const hasAdvanced = SETTINGS_SECTIONS.some((s) =>
      s.groups.some((g) => g.advanced !== undefined && g.advanced.length > 0),
    );
    expect(hasAdvanced).toBe(true);
  });

  it('select controls on search model fields carry reasoningKey', () => {
    const search = SETTINGS_SECTIONS.find((s) => s.id === 'search')!;
    const models = search.groups.find((g) => g.id === 'models')!;
    for (const field of models.fields) {
      if (field.control.kind === 'select') {
        expect(field.control.reasoningKey).toBeDefined();
        expect(field.control.reasoningOptions).toBeDefined();
      }
    }
  });

  it('OCR imaging group carries advanced fields with OCR_INCLUDE_PAGE_MODELS and OCR_REFUSAL_MARKERS', () => {
    const ocr = SETTINGS_SECTIONS.find((s) => s.id === 'ocr')!;
    const imaging = ocr.groups.find((g) => g.id === 'imaging')!;
    expect(imaging.advanced).toBeDefined();
    const advancedKeys = imaging.advanced!.map((f) => f.key);
    expect(advancedKeys).toContain('OCR_INCLUDE_PAGE_MODELS');
    expect(advancedKeys).toContain('OCR_REFUSAL_MARKERS');
  });

  // ── Embedding-provider decoupling assertions ──────────────────────────────

  it('embeddings group contains an EMBEDDING_PROVIDER segmented field as the first field', () => {
    const indexing = SETTINGS_SECTIONS.find((s) => s.id === 'indexing')!;
    const embeddings = indexing.groups.find((g) => g.id === 'embeddings')!;
    const providerField = embeddings.fields.find((f) => f.key === 'EMBEDDING_PROVIDER');
    expect(providerField).toBeDefined();
    expect(providerField!.control.kind).toBe('segmented');
    expect(embeddings.fields[0]!.key).toBe('EMBEDDING_PROVIDER');
  });

  it('EMBEDDING_PROVIDER segmented control has openai and ollama options', () => {
    const indexing = SETTINGS_SECTIONS.find((s) => s.id === 'indexing')!;
    const embeddings = indexing.groups.find((g) => g.id === 'embeddings')!;
    const providerField = embeddings.fields.find((f) => f.key === 'EMBEDDING_PROVIDER')!;
    expect(providerField.control.kind).toBe('segmented');
    if (providerField.control.kind === 'segmented') {
      const values = providerField.control.options.map((o) => o.value);
      expect(values).toContain('openai');
      expect(values).toContain('ollama');
    }
  });

  it('EMBEDDING_MODEL is a conditional control: select for OpenAI, text for Ollama', () => {
    const field = fieldByKey('EMBEDDING_MODEL')!;
    expect(field).toBeDefined();
    const control = field.control;
    expect(control.kind).toBe('conditional');
    if (control.kind === 'conditional') {
      expect(control.on).toBe('EMBEDDING_PROVIDER');
      expect(control.variants['openai']?.kind).toBe('select');
      expect(control.fallback.kind).toBe('text');
    }
  });

  it('connection card subtitles no longer imply one provider does both', () => {
    const connections = SETTINGS_SECTIONS.find((s) => s.id === 'connections')!;
    for (const id of ['openai', 'ollama']) {
      const group = connections.groups.find((g) => g.id === id)!;
      expect(group.subtitle).not.toMatch(/powers chat and embeddings/i);
      expect(group.subtitle).toMatch(/whichever you set to/i);
    }
  });

  it('provider group subtitle no longer mentions "always use OpenAI"', () => {
    const connections = SETTINGS_SECTIONS.find((s) => s.id === 'connections')!;
    const provider = connections.groups.find((g) => g.id === 'provider')!;
    expect(provider.subtitle).not.toMatch(/always use openai/i);
  });

  it('provider group subtitle mentions embeddings are configured separately', () => {
    const connections = SETTINGS_SECTIONS.find((s) => s.id === 'connections')!;
    const provider = connections.groups.find((g) => g.id === 'provider')!;
    expect(provider.subtitle).toMatch(/embeddings are configured separately/i);
  });

  it('allFieldKeys includes EMBEDDING_PROVIDER', () => {
    expect(allFieldKeys()).toContain('EMBEDDING_PROVIDER');
  });
});
