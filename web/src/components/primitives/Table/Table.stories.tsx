import type { Meta, StoryObj } from '@storybook/react';
import { Table } from './Table';
import type { Column } from './Table';

interface Person {
  id: number;
  name: string;
  role: string;
  seen: string;
}

const PEOPLE: Person[] = [
  { id: 1, name: 'Alex Morgan', role: 'Admin', seen: 'Now' },
  { id: 2, name: 'Sam Patel', role: 'Member', seen: '3h ago' },
  { id: 3, name: 'Robin Cho', role: 'Read-only', seen: '12 days ago' },
];

const COLUMNS: Column<Person>[] = [
  { key: 'name', header: 'Name', render: (p) => p.name },
  { key: 'role', header: 'Role', width: '120px', render: (p) => p.role },
  { key: 'seen', header: 'Last seen', render: (p) => p.seen },
  {
    key: 'actions',
    header: '',
    align: 'end',
    render: () => <button type="button">Edit</button>,
  },
];

const meta = {
  title: 'Primitives/Table',
  component: Table,
  parameters: { layout: 'padded' },
  tags: ['autodocs'],
} satisfies Meta<typeof Table>;

export default meta;

export const Default: StoryObj = {
  render: () => (
    <Table columns={COLUMNS} rows={PEOPLE} getRowKey={(p: Person) => p.id} />
  ),
};

export const WithMutedRow: StoryObj = {
  render: () => (
    <Table
      columns={COLUMNS}
      rows={PEOPLE}
      getRowKey={(p: Person) => p.id}
      isRowMuted={(p: Person) => p.id === 3}
    />
  ),
};

export const Empty: StoryObj = {
  render: () => (
    <Table
      columns={COLUMNS}
      rows={[]}
      getRowKey={(p: Person) => p.id}
      emptyMessage="No people yet — add the first one."
    />
  ),
};
