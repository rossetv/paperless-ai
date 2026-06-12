import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

// Vitest configuration — matches the CI lane described in CODE_GUIDELINES §12.10.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    // Thread workers share a process, so jsdom environment setup — the dominant
    // cost of this suite — is materially cheaper than the default 'forks' pool
    // (~27% faster locally). Per-file isolation stays ON: disabling it makes the
    // suite fail (cross-file global/DOM pollution), so do not add `isolate: false`.
    pool: 'threads',
    setupFiles: ['./src/test-setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'lcov'],
      // Only application source is measured. Stories are a catalogue, config
      // and the entry point are wiring, and ambient .d.ts files have no
      // executable code — counting them makes the percentage meaningless.
      include: ['src/**/*.{ts,tsx}'],
      exclude: [
        'src/**/*.test.{ts,tsx}',
        'src/**/*.stories.tsx',
        'src/main.tsx',
        'src/test-setup.ts',
        'src/**/*.d.ts',
      ],
      // Regression floor — set 2–3 points below measured baseline (June 2026):
      //   statements 93.25 %, branches 85.91 %, functions 93.61 %, lines 93.94 %
      // The gap prevents flakiness from tiny environment differences while still
      // catching a genuine drop (an untested new module, a deleted assertion).
      thresholds: {
        statements: 91,
        branches: 83,
        functions: 91,
        lines: 91,
      },
    },
  },
});
