// ESLint 9 flat config.
// Encodes the five-layer boundary rules from CODE_GUIDELINES §12.3.
import js from '@eslint/js';
import tsPlugin from '@typescript-eslint/eslint-plugin';
import tsParser from '@typescript-eslint/parser';
import boundaries from 'eslint-plugin-boundaries';
import reactPlugin from 'eslint-plugin-react';
import reactHooks from 'eslint-plugin-react-hooks';

/** @type {import('eslint').Linter.Config[]} */
export default [
  // Base JS recommended rules
  js.configs.recommended,

  // Global ignores
  {
    ignores: ['dist/**', 'node_modules/**', '.storybook/**', 'storybook-static/**'],
  },

  // TypeScript source files
  {
    files: ['src/**/*.{ts,tsx}'],
    languageOptions: {
      parser: tsParser,
      parserOptions: {
        ecmaVersion: 'latest',
        sourceType: 'module',
        ecmaFeatures: { jsx: true },
      },
    },
    plugins: {
      '@typescript-eslint': tsPlugin,
      boundaries,
      react: reactPlugin,
      'react-hooks': reactHooks,
    },
    settings: {
      // TypeScript-aware import resolver — required so eslint-plugin-boundaries
      // can resolve TS imports (no .js extension) to their absolute paths and
      // classify them into the correct layer.  Without this, the node resolver
      // fails to find .ts files, the dependency is marked UNKNOWN, and the
      // element-types rule silently skips it (§12.3).
      'import/resolver': {
        typescript: {
          alwaysTryTypes: true,
          project: './tsconfig.json',
        },
      },
      // Map src/ sub-directories to layer names used in boundary rules.
      'boundaries/elements': [
        { type: 'styles',     pattern: 'src/styles/**' },
        { type: 'components', pattern: 'src/components/**' },
        { type: 'api',        pattern: 'src/api/**' },
        { type: 'hooks',      pattern: 'src/hooks/**' },
        { type: 'features',   pattern: 'src/features/**' },
        { type: 'pages',      pattern: 'src/pages/**' },
      ],
      'boundaries/ignore': ['src/main.tsx', 'src/routes.tsx', 'src/App.tsx'],
    },
    rules: {
      // no-undef is redundant under TypeScript — tsc already proves every
      // identifier is defined, and the ESLint rule produces false positives on
      // browser and test globals. typescript-eslint advises disabling it.
      'no-undef': 'off',

      // TypeScript recommended rules (spread manually for flat-config compatibility)
      'no-unused-vars': 'off',
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
      '@typescript-eslint/no-explicit-any': 'error',

      // React
      'react/react-in-jsx-scope': 'off',
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',

      // Layer-boundary rules — CODE_GUIDELINES §12.3.
      // Dependency flow: pages → features → components → styles
      // api/ and hooks/ are cross-cutting leaves (importable by features and pages).
      'boundaries/element-types': [
        'error',
        {
          default: 'disallow',
          message:
            'Layer-boundary violation: ${file.type} cannot import from ${dependency.type}. ' +
            'Dependencies must flow downward only (CODE_GUIDELINES §12.3).',
          rules: [
            // styles/ imports nothing from other layers
            { from: 'styles',     allow: [] },
            // components/ may import other components and styles
            { from: 'components', allow: ['components', 'styles'] },
            // api/ and hooks/ are leaves — they import nothing from application layers
            { from: 'api',        allow: [] },
            { from: 'hooks',      allow: [] },
            // features/ imports components, api, hooks
            { from: 'features',   allow: ['components', 'api', 'hooks'] },
            // pages/ imports features, components/layout, api, hooks
            { from: 'pages',      allow: ['features', 'components', 'api', 'hooks'] },
          ],
        },
      ],
    },
  },
];
