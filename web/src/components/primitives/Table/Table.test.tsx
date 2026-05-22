import { render, screen, within } from '@testing-library/react';
import { Table } from './Table';
import type { Column } from './Table';

interface Row {
  id: number;
  name: string;
  age: number;
}

const ROWS: Row[] = [
  { id: 1, name: 'Alex', age: 30 },
  { id: 2, name: 'Sam', age: 24 },
];

const COLUMNS: Column<Row>[] = [
  { key: 'name', header: 'Name', render: (r) => r.name },
  { key: 'age', header: 'Age', align: 'end', render: (r) => String(r.age) },
];

describe('Table', () => {
  it('renders a semantic <table>', () => {
    render(<Table columns={COLUMNS} rows={ROWS} getRowKey={(r) => r.id} />);
    expect(screen.getByRole('table')).toBeInTheDocument();
  });

  it('renders one header cell per column', () => {
    render(<Table columns={COLUMNS} rows={ROWS} getRowKey={(r) => r.id} />);
    expect(screen.getByRole('columnheader', { name: 'Name' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Age' })).toBeInTheDocument();
  });

  it('renders one body row per data item', () => {
    render(<Table columns={COLUMNS} rows={ROWS} getRowKey={(r) => r.id} />);
    // 2 data rows + 1 header row
    expect(screen.getAllByRole('row')).toHaveLength(3);
  });

  it('renders each cell via the column render function', () => {
    render(<Table columns={COLUMNS} rows={ROWS} getRowKey={(r) => r.id} />);
    expect(screen.getByText('Alex')).toBeInTheDocument();
    expect(screen.getByText('24')).toBeInTheDocument();
  });

  it('renders the empty message when there are no rows', () => {
    render(
      <Table
        columns={COLUMNS}
        rows={[]}
        getRowKey={(r: Row) => r.id}
        emptyMessage="No people yet"
      />,
    );
    expect(screen.getByText('No people yet')).toBeInTheDocument();
    expect(screen.queryAllByRole('row')).toHaveLength(2); // header + empty row
  });

  it('applies a header label even when it is an empty string (actions column)', () => {
    const cols: Column<Row>[] = [
      ...COLUMNS,
      { key: 'actions', header: '', render: () => <button>Edit</button> },
    ];
    render(<Table columns={cols} rows={ROWS} getRowKey={(r) => r.id} />);
    const firstRow = screen.getAllByRole('row')[1] as HTMLElement;
    expect(within(firstRow).getByRole('button', { name: 'Edit' })).toBeInTheDocument();
  });

  it('marks the row with a data attribute when isRowMuted returns true', () => {
    render(
      <Table
        columns={COLUMNS}
        rows={ROWS}
        getRowKey={(r) => r.id}
        isRowMuted={(r) => r.id === 2}
      />,
    );
    const rows = screen.getAllByRole('row');
    // header row has no data-muted; row for Sam (id 2) does
    expect((rows[2] as HTMLElement).dataset['muted']).toBe('true');
    expect((rows[1] as HTMLElement).dataset['muted']).toBeUndefined();
  });

  it('forwards a custom className to the table element', () => {
    render(
      <Table columns={COLUMNS} rows={ROWS} getRowKey={(r) => r.id} className="extra" />,
    );
    expect(screen.getByRole('table').className).toContain('extra');
  });
});
