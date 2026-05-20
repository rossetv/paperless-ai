import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Tabs } from './Tabs';

const TABS = [
  { id: 'results', label: 'Results', content: <p>Search results here</p> },
  { id: 'sources', label: 'Sources', content: <p>Source documents here</p> },
  { id: 'plan', label: 'Query plan', content: <p>Query plan details here</p> },
];

describe('Tabs', () => {
  it('renders all tab labels in a tablist', () => {
    render(<Tabs tabs={TABS} />);
    const tablist = screen.getByRole('tablist');
    expect(tablist).toBeInTheDocument();
    const tabs = screen.getAllByRole('tab');
    expect(tabs).toHaveLength(3);
    expect(tabs[0]).toHaveTextContent('Results');
    expect(tabs[1]).toHaveTextContent('Sources');
    expect(tabs[2]).toHaveTextContent('Query plan');
  });

  it('shows the first tab panel by default', () => {
    render(<Tabs tabs={TABS} />);
    expect(screen.getByText('Search results here')).toBeInTheDocument();
    expect(screen.queryByText('Source documents here')).not.toBeInTheDocument();
  });

  it('shows the second panel when the second tab is clicked', async () => {
    render(<Tabs tabs={TABS} />);
    await userEvent.click(screen.getByRole('tab', { name: 'Sources' }));
    expect(screen.getByText('Source documents here')).toBeInTheDocument();
    expect(screen.queryByText('Search results here')).not.toBeInTheDocument();
  });

  it('marks the active tab with aria-selected="true"', () => {
    render(<Tabs tabs={TABS} />);
    expect(screen.getByRole('tab', { name: 'Results' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    expect(screen.getByRole('tab', { name: 'Sources' })).toHaveAttribute(
      'aria-selected',
      'false',
    );
  });

  it('updates aria-selected when a different tab is clicked', async () => {
    render(<Tabs tabs={TABS} />);
    await userEvent.click(screen.getByRole('tab', { name: 'Sources' }));
    expect(screen.getByRole('tab', { name: 'Sources' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    expect(screen.getByRole('tab', { name: 'Results' })).toHaveAttribute(
      'aria-selected',
      'false',
    );
  });

  it('each tab has role="tab" and each panel has role="tabpanel"', () => {
    render(<Tabs tabs={TABS} />);
    const tabs = screen.getAllByRole('tab');
    expect(tabs).toHaveLength(3);
    const panels = screen.getAllByRole('tabpanel');
    expect(panels).toHaveLength(1); // only the active panel is rendered
  });

  it('moves focus right with ArrowRight key', async () => {
    render(<Tabs tabs={TABS} />);
    const [firstTab, secondTab] = screen.getAllByRole('tab');
    firstTab.focus();
    await userEvent.keyboard('{ArrowRight}');
    expect(secondTab).toHaveFocus();
  });

  it('moves focus left with ArrowLeft key', async () => {
    render(<Tabs tabs={TABS} />);
    const [firstTab, secondTab] = screen.getAllByRole('tab');
    secondTab.focus();
    await userEvent.keyboard('{ArrowLeft}');
    expect(firstTab).toHaveFocus();
  });

  it('wraps focus from last to first tab with ArrowRight', async () => {
    render(<Tabs tabs={TABS} />);
    const tabs = screen.getAllByRole('tab');
    tabs[2].focus();
    await userEvent.keyboard('{ArrowRight}');
    expect(tabs[0]).toHaveFocus();
  });

  it('wraps focus from first to last tab with ArrowLeft', async () => {
    render(<Tabs tabs={TABS} />);
    const tabs = screen.getAllByRole('tab');
    tabs[0].focus();
    await userEvent.keyboard('{ArrowLeft}');
    expect(tabs[2]).toHaveFocus();
  });

  it('activates the focused tab when Enter is pressed', async () => {
    render(<Tabs tabs={TABS} />);
    const [, secondTab] = screen.getAllByRole('tab');
    secondTab.focus();
    await userEvent.keyboard('{Enter}');
    expect(screen.getByText('Source documents here')).toBeInTheDocument();
  });

  it('activates the focused tab when Space is pressed', async () => {
    render(<Tabs tabs={TABS} />);
    const [, , thirdTab] = screen.getAllByRole('tab');
    thirdTab.focus();
    await userEvent.keyboard(' ');
    expect(screen.getByText('Query plan details here')).toBeInTheDocument();
  });

  it('respects defaultActiveId prop', () => {
    render(<Tabs tabs={TABS} defaultActiveId="sources" />);
    expect(screen.getByText('Source documents here')).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Sources' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
  });
});
