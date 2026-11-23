/**
 * True below SearchScreenLayout's 834px breakpoint, where the filter rail stacks
 * above the content. matchMedia is missing in some test environments.
 */
export function isNarrowViewport(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(max-width: 834px)').matches
  );
}
