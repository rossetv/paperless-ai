import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// The built output is served by the Python search server at '/'.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: 'dist',
    // Keeps the image lean and the source unpublished; 'hidden' would still
    // allow symbolicated traces in a private error tracker.
    sourcemap: false,
    // Matches tsconfig and the single modern browser it runs in, so Vite emits
    // no down-level helpers. It is also the CSS target: the minifier adds the
    // -webkit- prefixes it needs, and drops a standard declaration that a
    // hand-written prefixed one follows.
    target: 'es2022',
  },
  server: {
    port: 3000,
    proxy: {
      '/api': 'http://localhost:8080',
    },
  },
});
