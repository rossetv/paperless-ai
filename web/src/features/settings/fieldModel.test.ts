import { describe, it, expect } from 'vitest';
import {
  SETTINGS_SECTIONS,
  allFieldKeys,
  fieldByKey,
  parseValue,
  serialiseValue,
} from './fieldModel';

describe('settings field model', () => {
  it('defines exactly eight sections', () => {
    expect(SETTINGS_SECTIONS).toHaveLength(8);
  });

  it('uses the eight expected section anchor ids in pipeline order', () => {
    expect(SETTINGS_SECTIONS.map((s) => s.id)).toEqual([
      'connections',
      'providers',
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

  it('structures connections into paperless/openai/ollama groups (no provider strip)', () => {
    const connections = SETTINGS_SECTIONS.find((s) => s.id === 'connections')!;
    const groupIds = connections.groups.map((g) => g.id);
    expect(groupIds).toEqual(['paperless', 'openai', 'ollama']);
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

  // ── AI providers section: independent role selectors ──────────────────────

  it("the 'providers' section sits immediately after 'connections' and before 'ocr'", () => {
    const ids = SETTINGS_SECTIONS.map((s) => s.id);
    expect(ids.indexOf('providers')).toBe(ids.indexOf('connections') + 1);
    expect(ids.indexOf('providers')).toBe(ids.indexOf('ocr') - 1);
  });

  it("the 'providers' section subtitle is correct", () => {
    const providers = SETTINGS_SECTIONS.find((s) => s.id === 'providers')!;
    expect(providers.subtitle).toBe(
      'Which provider serves each role. The two are set independently.',
    );
  });

  it("the 'providers' section has exactly two groups: 'chat' and 'embeddings'", () => {
    const providers = SETTINGS_SECTIONS.find((s) => s.id === 'providers')!;
    expect(providers.title).toBe('AI providers');
    expect(providers.groups.map((g) => g.id)).toEqual(['chat', 'embeddings']);
  });

  it("the 'chat' group has correct title, subtitle, and LLM_PROVIDER as a 'Provider' segmented", () => {
    const providers = SETTINGS_SECTIONS.find((s) => s.id === 'providers')!;
    const chat = providers.groups.find((g) => g.id === 'chat')!;
    expect(chat.title).toBe('Chat & vision');
    expect(chat.subtitle).toBe(
      'Runs OCR transcription, classification, and search answers.',
    );
    expect(chat.fields).toHaveLength(1);
    const field = chat.fields[0]!;
    expect(field.key).toBe('LLM_PROVIDER');
    expect(field.label).toBe('Provider');
    expect(field.control.kind).toBe('segmented');
    if (field.control.kind === 'segmented') {
      expect(field.control.options.map((o) => o.value)).toEqual(['openai', 'ollama']);
    }
  });

  it("the 'embeddings' group has correct title, subtitle, and EMBEDDING_PROVIDER as a 'Provider' segmented", () => {
    const providers = SETTINGS_SECTIONS.find((s) => s.id === 'providers')!;
    const embeddings = providers.groups.find((g) => g.id === 'embeddings')!;
    expect(embeddings.title).toBe('Embeddings');
    expect(embeddings.subtitle).toBe(
      'Vectorises your library for semantic search. Switching this re-embeds every document.',
    );
    expect(embeddings.fields).toHaveLength(1);
    const field = embeddings.fields[0]!;
    expect(field.key).toBe('EMBEDDING_PROVIDER');
    expect(field.label).toBe('Provider');
    expect(field.control.kind).toBe('segmented');
    if (field.control.kind === 'segmented') {
      expect(field.control.options.map((o) => o.value)).toEqual(['openai', 'ollama']);
    }
  });

  it("the indexing/embeddings group subtitle cross-references AI providers (regression pin)", () => {
    const indexing = SETTINGS_SECTIONS.find((s) => s.id === 'indexing')!;
    const embeddings = indexing.groups.find((g) => g.id === 'embeddings')!;
    expect(embeddings.subtitle).toBe(
      'Changing the model or dimensions triggers a full rebuild. The provider lives under AI providers.',
    );
  });

  it('EMBEDDING_PROVIDER no longer lives in the indexing/embeddings group', () => {
    const indexing = SETTINGS_SECTIONS.find((s) => s.id === 'indexing')!;
    const embeddings = indexing.groups.find((g) => g.id === 'embeddings')!;
    expect(embeddings.fields.map((f) => f.key)).not.toContain('EMBEDDING_PROVIDER');
  });

  it('the indexing/embeddings group still holds EMBEDDING_MODEL and EMBEDDING_DIMENSIONS', () => {
    const indexing = SETTINGS_SECTIONS.find((s) => s.id === 'indexing')!;
    const embeddings = indexing.groups.find((g) => g.id === 'embeddings')!;
    const keys = embeddings.fields.map((f) => f.key);
    expect(keys).toContain('EMBEDDING_MODEL');
    expect(keys).toContain('EMBEDDING_DIMENSIONS');
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

  it('connection card subtitles are neutral, with no role-selection language', () => {
    const connections = SETTINGS_SECTIONS.find((s) => s.id === 'connections')!;
    const openai = connections.groups.find((g) => g.id === 'openai')!;
    const ollama = connections.groups.find((g) => g.id === 'ollama')!;

    // No "whichever you set to" / "selected provider" phrasing — the cards now
    // describe the service itself, not which role it serves.
    for (const group of [openai, ollama]) {
      expect(group.subtitle).not.toMatch(/whichever you set to/i);
      expect(group.subtitle).not.toMatch(/selected provider/i);
    }
    expect(openai.subtitle).toBe("OpenAI's hosted chat, vision and embedding API.");
    expect(ollama.subtitle).toBe('A local Ollama server (OpenAI-compatible endpoint).');
  });

  it("connections no longer has a 'provider' group (the strip moved to AI providers)", () => {
    const connections = SETTINGS_SECTIONS.find((s) => s.id === 'connections')!;
    expect(connections.groups.find((g) => g.id === 'provider')).toBeUndefined();
  });

  it('allFieldKeys includes EMBEDDING_PROVIDER', () => {
    expect(allFieldKeys()).toContain('EMBEDDING_PROVIDER');
  });
});
