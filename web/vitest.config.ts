import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    // jsdom setup dominates this suite and is cheaper in threads than in the
    // default 'forks' pool (~27% faster). Do not add `isolate: false`: cross-file
    // DOM pollution makes the suite fail.
    pool: 'threads',
    setupFiles: ['./src/test-setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'lcov'],
      // Stories, wiring and .d.ts files have no logic worth measuring.
      include: ['src/**/*.{ts,tsx}'],
      exclude: [
        'src/**/*.test.{ts,tsx}',
        'src/**/*.stories.tsx',
        'src/main.tsx',
        'src/test-setup.ts',
        'src/**/*.d.ts',
      ],
      // Regression floor 2-3 points below the measured baseline, so small
      // environment differences do not flake but a real drop still fails.
      thresholds: {
        statements: 91,
        branches: 83,
        functions: 91,
        lines: 91,
      },
    },
  },
});
