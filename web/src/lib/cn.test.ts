import { describe, it, expect } from 'vitest';
import { cn } from './cn';

describe('cn', () => {
  it('joins multiple class names with a single space', () => {
    expect(cn('a', 'b', 'c')).toBe('a b c');
  });

  it('drops false values', () => {
    expect(cn('a', false, 'b')).toBe('a b');
  });

  it('drops null and undefined values', () => {
    expect(cn('a', null, 'b', undefined)).toBe('a b');
  });

  it('drops empty strings', () => {
    expect(cn('a', '', 'b')).toBe('a b');
  });

  it('returns an empty string when given no arguments', () => {
    expect(cn()).toBe('');
  });

  it('returns an empty string when every part is falsy', () => {
    expect(cn(false, null, undefined, '')).toBe('');
  });

  it('keeps a single class name unchanged', () => {
    expect(cn('only')).toBe('only');
  });

  it('supports the conditional-modifier idiom', () => {
    const active = true;
    const disabled = false;
    expect(cn('base', active && 'is-active', disabled && 'is-disabled')).toBe(
      'base is-active',
    );
  });
});
