import { describe, it, expect } from 'vitest';
import {
  SETTINGS_SECTIONS,
  allFieldKeys,
  fieldByKey,
  parseValue,
  serialiseValue,
} from './fieldModel';

describe('settings field model', () => {
  it('defines exactly nine sections', () => {
    expect(SETTINGS_SECTIONS).toHaveLength(9);
  });

  it('gives every section a stable anchor id and a title', () => {
    for (const section of SETTINGS_SECTIONS) {
      expect(section.id).toMatch(/^[a-z]+$/);
      expect(section.title.length).toBeGreaterThan(0);
      expect(section.groups.length).toBeGreaterThan(0);
    }
  });

  it('uses the nine expected section anchor ids', () => {
    expect(SETTINGS_SECTIONS.map((s) => s.id)).toEqual([
      'paperless',
      'llm',
      'search',
      'embed',
      'ocr',
      'classify',
      'tags',
      'perf',
      'logs',
    ]);
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
        for (const field of group.fields) {
          expect(field.label.length).toBeGreaterThan(0);
          expect(field.control.kind).toBeTruthy();
        }
      }
    }
  });

  it('gives every number field a finite minimum', () => {
    for (const section of SETTINGS_SECTIONS) {
      for (const group of section.groups) {
        for (const field of group.fields) {
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
          const f = group.fields.find((field) => field.key === k);
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
    const listField = fieldByKey('AI_MODELS')!;
    expect(parseValue(listField, 'a, b ,c')).toEqual(['a', 'b', 'c']);
    const textField = fieldByKey('PAPERLESS_URL')!;
    expect(parseValue(textField, 'http://x')).toBe('http://x');
  });

  it('parses a null wire value to the control empty value', () => {
    expect(parseValue(fieldByKey('SEARCH_TOP_K')!, null)).toBe(0);
    expect(parseValue(fieldByKey('AI_MODELS')!, null)).toEqual([]);
    expect(parseValue(fieldByKey('PAPERLESS_URL')!, null)).toBe('');
  });

  it('serialises a typed value back to a wire string', () => {
    expect(serialiseValue(25)).toBe('25');
    expect(serialiseValue(true)).toBe('true');
    expect(serialiseValue(false)).toBe('false');
    expect(serialiseValue(['a', 'b'])).toBe('a, b');
    expect(serialiseValue('http://x')).toBe('http://x');
  });

  it('places PAPERLESS_URL in the paperless/endpoint group', () => {
    const paperless = SETTINGS_SECTIONS.find((s) => s.id === 'paperless')!;
    const endpoint = paperless.groups.find((g) => g.id === 'endpoint')!;
    expect(endpoint.fields.map((f) => f.key)).toContain('PAPERLESS_URL');
  });

  it('splits llm into provider, credentials, and models groups', () => {
    const llm = SETTINGS_SECTIONS.find((s) => s.id === 'llm')!;
    const groupIds = llm.groups.map((g) => g.id);
    expect(groupIds).toEqual(['provider', 'credentials', 'models']);
  });

  it('fieldByKey resolves a key nested inside any group', () => {
    expect(fieldByKey('EMBEDDING_MODEL')).toBeDefined();
    expect(fieldByKey('EMBEDDING_MODEL')?.key).toBe('EMBEDDING_MODEL');
    expect(fieldByKey('ERROR_TAG_ID')).toBeDefined();
    expect(fieldByKey('__unknown__')).toBeUndefined();
  });
});
