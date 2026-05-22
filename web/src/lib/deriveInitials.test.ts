import { deriveInitials } from './deriveInitials';

describe('deriveInitials', () => {
  it('returns initials from a two-word display name', () => {
    expect(deriveInitials('Alex Morgan', 'alex.morgan')).toBe('AM');
  });

  it('uppercases the initials', () => {
    expect(deriveInitials('alex morgan', 'alex')).toBe('AM');
  });

  it('falls back to the username when display_name is null', () => {
    // 'alex.morgan' splits on '.' → ['alex', 'morgan'] → 'AM'
    expect(deriveInitials(null, 'alex.morgan')).toBe('AM');
  });

  it('handles a single-word name with first two letters', () => {
    expect(deriveInitials('Alex', 'alex')).toBe('AL');
  });

  it('splits on dots in the username', () => {
    // 'alex.morgan' splits on '.' → ['alex', 'morgan'] → first letters 'A' + 'M' = 'AM'
    expect(deriveInitials(null, 'alex.morgan')).toBe('AM');
  });

  it('splits on underscores', () => {
    expect(deriveInitials('alex_morgan', 'alex')).toBe('AM');
  });

  it('splits on hyphens', () => {
    expect(deriveInitials('alex-morgan', 'alex')).toBe('AM');
  });

  it('handles the legacy API key display name', () => {
    expect(deriveInitials('Legacy API key', 'legacy')).toBe('LA');
  });

  it('returns "?" for an empty display name and empty username', () => {
    expect(deriveInitials('', '')).toBe('?');
  });

  it('returns "?" for a whitespace-only display name and empty username', () => {
    expect(deriveInitials('   ', '')).toBe('?');
  });
});
