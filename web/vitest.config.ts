import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

// Vitest configuration — matches the CI lane described in CODE_GUIDELINES §12.10.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
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
      // A regression floor (CODE_GUIDELINES §11). The suite currently covers
      // ~99% of statements; this floor sits below that with headroom, so a
      // genuine drop — an empty test file, a deleted assertion, an untested
      // new module — fails the lane instead of passing silently.
      thresholds: {
        statements: 90,
        branches: 85,
        functions: 90,
        lines: 90,
      },
    },
  },
});
