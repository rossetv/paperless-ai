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
      // Map src/ sub-directories to layer names used in the boundary rules.
      //
      // Each layer of the §12.3 stack is its OWN element type — the three
      // component tiers (primitives / layout / patterns) are distinct, not
      // collapsed into one `components`, because §12.3 forbids a page from
      // reaching a primitive directly while allowing it to reach layout.
      // A single `components` type cannot express that.
      //
      // Order matters: eslint-plugin-boundaries matches the FIRST pattern, so
      // the three specific `src/components/<tier>/**` globs are listed before
      // any broader path could shadow them.
      //
      // The composition root — App.tsx, routes.tsx, main.tsx — is classified
      // as the `app` element type (NOT ignored), so its imports are still
      // checked against the matrix.
      'boundaries/elements': [
        { type: 'styles',               pattern: 'src/styles/**' },
        // lib/ — framework-agnostic leaf helpers (e.g. the `cn` class-name
        // join). Imports nothing; importable by every layer, so it sits next
        // to styles/ at the bottom of the stack (§12.3).
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
      //
      // The stack flows strictly downward. Within components/, the three tiers
      // also form a downward stack: patterns → layout → primitives → styles.
      //
      //   app          → pages, features, api, hooks, styles
      //   pages        → features, components-layout, api, hooks  (NOT primitives, NOT patterns)
      //   features     → any components-*, api, hooks, styles
      //   patterns     → patterns, layout, primitives, styles
      //   layout       → layout, primitives, styles
      //   primitives   → primitives, styles
      //   api / hooks  → leaves: nothing from application layers
      //   styles       → nothing
      //
      // A type may always import its own type (a primitive importing another
      // primitive, etc.) — that is intra-layer composition, not a boundary cross.
      'boundaries/element-types': [
        'error',
        {
          default: 'disallow',
          message:
            'Layer-boundary violation: ${file.type} cannot import from ${dependency.type}. ' +
            'Dependencies must flow downward only (CODE_GUIDELINES §12.3).',
          rules: [
            // styles/ — the bottom of the stack; imports nothing.
            { from: 'styles', allow: [] },

            // lib/ — framework-agnostic leaf helpers; imports nothing, exactly
            // like styles/. Every layer above may import it.
            { from: 'lib', allow: [] },

            // Component tiers — each may import lower tiers, styles, and lib.
            { from: 'components-primitives', allow: ['components-primitives', 'styles', 'lib'] },
            {
              from: 'components-layout',
              allow: ['components-layout', 'components-primitives', 'styles', 'lib'],
            },
            {
              from: 'components-patterns',
              allow: [
                'components-patterns',
                'components-layout',
                'components-primitives',
                'styles',
                'lib',
              ],
            },

            // api/ and hooks/ — cross-cutting leaves; no application-layer
            // imports, but the framework-agnostic lib/ leaf is allowed.
            { from: 'api', allow: ['api', 'lib'] },
            { from: 'hooks', allow: ['hooks', 'lib'] },

            // features/ — the only layer that knows the domain; may use any
            // component tier plus the cross-cutting leaves and styles.
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

            // pages/ — compose features + layout only. A page may NOT reach a
            // primitive or a pattern directly: a missing visual must become a
            // feature, never be solved on the page. This is the structural
            // guarantee against per-page design drift (§12.3).
            {
              from: 'pages',
              allow: ['pages', 'features', 'components-layout', 'api', 'hooks', 'lib'],
            },

            // app/ — the composition root: routes + providers. Mounts pages and
            // features, wires the API/hooks, and pulls in global styles.
            {
              from: 'app',
              allow: ['app', 'pages', 'features', 'api', 'hooks', 'styles', 'lib'],
            },
          ],
        },
      ],
    },
  },
];
