// ESLint flat config, including the layer-boundary rules for src/.
import js from '@eslint/js';
import tsPlugin from '@typescript-eslint/eslint-plugin';
import tsParser from '@typescript-eslint/parser';
import boundaries from 'eslint-plugin-boundaries';
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
      ],
      'boundaries/files': [
        { category: 'app', pattern: ['src/App.tsx', 'src/routes.tsx', 'src/main.tsx'] },
      ],
    },
    rules: {
      // tsc already checks identifiers; this rule false-positives on globals.
      'no-undef': 'off',

      'no-unused-vars': 'off',
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
      '@typescript-eslint/no-explicit-any': 'error',

      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'error',

      // Imports flow downward only; within components/ the tiers stack as
      // patterns → layout → primitives. hooks/, styles/ and lib/ are leaves
      // every component tier may use.
      // Imports flow downward only; within components/ the tiers stack as
      // patterns → layout → primitives. hooks/, styles/ and lib/ are leaves
      // every component tier may use.
      'boundaries/dependencies': [
        'error',
        {
          default: 'disallow',
          message:
            'Layer-boundary violation: {{ from.element.type }} cannot import from {{ to.element.type }}. ' +
            'Dependencies must flow downward only.',
          policies: [
            // styles/ has no policy: under the default it imports nothing.
            // api/ for type-only deps (parseSearchParams returns FilterRequest).
            {
              from: { element: { type: 'lib' } },
              allow: { to: { element: { types: ['api'] } } },
            },
            {
              from: { element: { type: 'components-primitives' } },
              allow: { to: { element: { types: ['components-primitives', 'hooks', 'styles', 'lib'] } } },
            },
            {
              from: { element: { type: 'components-layout' } },
              allow: { to: { element: { types: ['components-layout', 'components-primitives', 'hooks', 'styles', 'lib'] } } },
            },
            // Narrow exception: connected patterns such as FilterControls
            // use their own api hooks and types, so api is last.
            {
              from: { element: { type: 'components-patterns' } },
              allow: { to: { element: { types: ['components-patterns', 'components-layout', 'components-primitives', 'hooks', 'styles', 'lib', 'api'] } } },
            },
            {
              from: { element: { type: 'api' } },
              allow: { to: { element: { types: ['api', 'lib'] } } },
            },
            // api/ so domain hooks such as useAuth can wrap its query hooks.
            {
              from: { element: { type: 'hooks' } },
              allow: { to: { element: { types: ['hooks', 'api', 'lib'] } } },
            },
            {
              from: { element: { type: 'features' } },
              allow: { to: { element: { types: ['features', 'components-patterns', 'components-layout', 'components-primitives', 'api', 'hooks', 'styles', 'lib'] } } },
            },
            // No primitives or patterns: a missing visual becomes a feature
            // rather than being built on the page, which prevents design drift.
            {
              from: { element: { type: 'pages' } },
              allow: { to: { element: { types: ['pages', 'features', 'components-layout', 'api', 'hooks', 'lib'] } } },
            },
            // components-layout for the FullPageLoading screen shown before any
            // page mounts.
            {
              from: { file: { categories: 'app' } },
              allow: [
                { to: { file: { categories: 'app' } } },
                { to: { element: { types: ['pages', 'features', 'components-layout', 'api', 'hooks', 'styles', 'lib'] } } },
              ],
            },
          ],
        },
      ],
    },
  },
];
