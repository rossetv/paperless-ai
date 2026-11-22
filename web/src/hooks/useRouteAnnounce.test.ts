import { pageName } from './useRouteAnnounce';

describe('pageName', () => {
  it.each([
    ['/', 'Search'],
    ['/library', 'Library'],
    ['/library/document/12', 'Document'],
    ['/document/12', 'Document'],
    ['/settings/keys', 'API Keys'],
    ['/login', 'Sign in'],
  ])('names %s', (path, name) => {
    expect(pageName(path)).toBe(name);
  });

  it('has no name for an unknown path', () => {
    expect(pageName('/nope')).toBeUndefined();
  });
});
