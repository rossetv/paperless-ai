import type { Preview } from '@storybook/react';

// Pulls in the design system — tokens.css, themes.css, global resets — so every
// story renders with the same design values the app uses. Without this, stories
// that reference var(--…) tokens render unstyled.
import '../src/styles/global.css';

const preview: Preview = {
  parameters: {
    controls: {
      matchers: {
        colour: /(colour|color)$/i,
        date: /Date$/i,
      },
    },
  },
};

export default preview;
