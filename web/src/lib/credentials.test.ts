import { validateUsername, validatePassword } from './credentials';

describe('validateUsername', () => {
  it('accepts a valid username', () => {
    expect(validateUsername('alex.morgan')).toBeUndefined();
  });

  it('accepts the minimum length (3)', () => {
    expect(validateUsername('abc')).toBeUndefined();
  });

  it('accepts the maximum length (64)', () => {
    expect(validateUsername('a'.repeat(64))).toBeUndefined();
  });

  it('rejects a username shorter than 3 characters', () => {
    expect(validateUsername('ab')).toMatch(/between 3 and 64 characters/i);
  });

  it('rejects a username longer than 64 characters', () => {
    expect(validateUsername('a'.repeat(65))).toMatch(/between 3 and 64 characters/i);
  });

  it('rejects a username with spaces', () => {
    expect(validateUsername('alex morgan')).toMatch(/letters, numbers/i);
  });

  it('rejects a username with illegal punctuation', () => {
    expect(validateUsername('alex!')).toMatch(/letters, numbers/i);
  });

  it('accepts dots, underscores and hyphens', () => {
    expect(validateUsername('a.b_c-d')).toBeUndefined();
  });
});

describe('validatePassword', () => {
  it('accepts a password of exactly 12 characters', () => {
    expect(validatePassword('123456789012')).toBeUndefined();
  });

  it('accepts a password longer than 12 characters', () => {
    expect(validatePassword('a-long-password')).toBeUndefined();
  });

  it('rejects a password shorter than 12 characters', () => {
    expect(validatePassword('short')).toMatch(/at least 12 characters/i);
  });

  it('rejects a password of exactly 11 characters (one below the floor)', () => {
    expect(validatePassword('12345678901')).toMatch(/at least 12 characters/i);
  });

  it('rejects an empty password', () => {
    expect(validatePassword('')).toMatch(/at least 12 characters/i);
  });
});
