import React, { useState } from 'react';
import type { Meta, StoryObj } from '@storybook/react';
import { Button } from '../../primitives/Button/Button';
import { Modal } from './Modal';

const meta = {
  title: 'Patterns/Modal',
  component: Modal,
  parameters: {
    layout: 'centered',
  },
  tags: ['autodocs'],
  argTypes: {
    isOpen: { control: 'boolean' },
    title: { control: 'text' },
  },
} satisfies Meta<typeof Modal>;

export default meta;
type Story = StoryObj<typeof meta>;

/** Static snapshot — isOpen controlled via the args panel. */
export const Default: Story = {
  args: {
    isOpen: true,
    title: 'Confirm action',
    onClose: () => {
      /* story — noop */
    },
    children: <p>Are you sure you want to delete this document? This action cannot be undone.</p>,
  },
};

/** Interactive — open/close via a trigger button. */
export const WithTrigger: Story = {
  render: function Render() {
    const [open, setOpen] = useState(false);
    return (
      <>
        <Button onClick={() => setOpen(true)}>Open modal</Button>
        <Modal isOpen={open} title="Details" onClose={() => setOpen(false)}>
          <p>This modal was opened by clicking the button above.</p>
          <p>Press Escape or click outside to dismiss it.</p>
          <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '1rem' }}>
            <Button onClick={() => setOpen(false)}>Close</Button>
          </div>
        </Modal>
      </>
    );
  },
  args: {
    isOpen: false,
    title: '',
    children: null,
    onClose: () => {
      /* story — noop */
    },
  },
};

/** Long content — verifies scrolling behaviour inside the panel. */
export const LongContent: Story = {
  args: {
    isOpen: true,
    title: 'Long scrollable content',
    onClose: () => {
      /* story — noop */
    },
    children: Array.from({ length: 20 }, (_, i) => (
      <p key={i}>
        Paragraph {i + 1} — Lorem ipsum dolor sit amet, consectetur adipiscing elit.
      </p>
    )),
  },
};
