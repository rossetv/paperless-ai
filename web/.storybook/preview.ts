import type { Preview } from '@storybook/react';

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
