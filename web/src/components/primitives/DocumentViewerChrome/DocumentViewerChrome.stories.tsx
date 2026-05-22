import type { Meta, StoryObj } from '@storybook/react';
import { DocumentViewerChrome } from './DocumentViewerChrome';

const meta = {
  title: 'Primitives/DocumentViewerChrome',
  component: DocumentViewerChrome,
  parameters: { layout: 'fullscreen' },
  args: { onClose: () => globalThis.console.log('close') },
} satisfies Meta<typeof DocumentViewerChrome>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: {
    title: 'Annual energy statement — 12 months to 31 Dec 2024',
    paperlessUrl: 'https://paperless.example.com/documents/9823/',
    downloadUrl: '/api/documents/9823/pdf',
    children: (
      <div
        style={{
          height: '480px',
          background: 'var(--colour-dark-surface)',
        }}
      />
    ),
  },
};
