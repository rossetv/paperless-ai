// ESLint 9 flat config, including the layer-boundary rules for src/.
import js from '@eslint/js';
import tsPlugin from '@typescript-eslint/eslint-plugin';
import tsParser from '@typescript-eslint/parser';
import boundaries from 'eslint-plugin-boundaries';
import reactPlugin from 'eslint-plugin-react';
import reactHooks from 'eslint-plugin-react-hooks';

/** @type {import('eslint').Linter.Config[]} */
export default [
  js.configs.recommended,

  {
    ignores: ['dist/**', 'node_modules/**', '.storybook/**', 'storybook-static/**'],
  },

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
      // Without a TS resolver, boundaries cannot resolve extensionless TS
      // imports, marks them UNKNOWN, and silently skips them.
      'import/resolver': {
        typescript: {
          alwaysTryTypes: true,
          project: './tsconfig.json',
        },
      },
      // The component tiers are separate types because a page may reach layout
      // but not a primitive. boundaries matches the first pattern, so the
      // specific component globs must come before any broader one. The
      // composition root is typed `app`, not ignored, so its imports are checked.
      'boundaries/elements': [
        { type: 'styles',               pattern: 'src/styles/**' },
        { type: 'lib',                  pattern: 'src/lib/**' },
        { type: 'components-primitives', pattern: 'src/components/primitives/**' },
        { type: 'components-layout',     pattern: 'src/components/layout/**' },
        { type: 'components-patterns',   pattern: 'src/components/patterns/**' },
        { type: 'api',                   pattern: 'src/api/**' },
        { type: 'hooks',                 pattern: 'src/hooks/**' },
        { type: 'features',              pattern: 'src/features/**' },
        { type: 'pages',                 pattern: 'src/pages/**' },
        {
          type: 'app',
          mode: 'full',
          pattern: ['src/App.tsx', 'src/routes.tsx', 'src/main.tsx'],
        },
      ],
    },
    rules: {
      // tsc already checks identifiers; this rule false-positives on globals.
      'no-undef': 'off',

      'no-unused-vars': 'off',
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
      '@typescript-eslint/no-explicit-any': 'error',

      'react/react-in-jsx-scope': 'off',
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'error',

      // Imports flow downward only; within components/ the tiers stack as
      // patterns → layout → primitives. hooks/, styles/ and lib/ are leaves
      // every component tier may use.
      'boundaries/element-types': [
        'error',
        {
          default: 'disallow',
          message:
            'Layer-boundary violation: ${file.type} cannot import from ${dependency.type}. ' +
            'Dependencies must flow downward only.',
          rules: [
            { from: 'styles', allow: [] },

            // api/ for type-only deps (parseSearchParams returns FilterRequest).
            { from: 'lib', allow: ['api'] },

            {
              from: 'components-primitives',
              allow: ['components-primitives', 'hooks', 'styles', 'lib'],
            },
            {
              from: 'components-layout',
              allow: ['components-layout', 'components-primitives', 'hooks', 'styles', 'lib'],
            },
            {
              from: 'components-patterns',
              allow: [
                'components-patterns',
                'components-layout',
                'components-primitives',
                'hooks',
                'styles',
                'lib',
                // Narrow exception: connected patterns such as FilterControls
                // use their own api hooks and types.
                'api',
              ],
            },

            { from: 'api', allow: ['api', 'lib'] },

            // api/ so domain hooks such as useAuth can wrap its query hooks.
            { from: 'hooks', allow: ['hooks', 'api', 'lib'] },

            {
              from: 'features',
              allow: [
                'features',
                'components-patterns',
                'components-layout',
                'components-primitives',
                'api',
                'hooks',
                'styles',
                'lib',
              ],
            },

            // No primitives or patterns: a missing visual becomes a feature
            // rather than being built on the page, which prevents design drift.
            {
              from: 'pages',
              allow: ['pages', 'features', 'components-layout', 'api', 'hooks', 'lib'],
            },

            // components-layout for the FullPageLoading screen shown before any
            // page mounts.
            {
              from: 'app',
              allow: ['app', 'pages', 'features', 'components-layout', 'api', 'hooks', 'styles', 'lib'],
            },
          ],
        },
      ],
    },
  },
];
