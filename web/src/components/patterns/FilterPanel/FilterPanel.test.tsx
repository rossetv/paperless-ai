import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { FilterPanel } from './FilterPanel';

describe('FilterPanel', () => {
  it('renders the panel title', () => {
    render(
      <FilterPanel title="Date range">
        <p>Filter content</p>
      </FilterPanel>,
    );
    expect(screen.getByText('Date range')).toBeInTheDocument();
  });

  it('is expanded by default', () => {
    render(
      <FilterPanel title="Filters">
        <p>Visible content</p>
      </FilterPanel>,
    );
    expect(screen.getByText('Visible content')).toBeVisible();
  });

  it('can start collapsed when defaultExpanded is false', () => {
    render(
      <FilterPanel title="Filters" defaultExpanded={false}>
        <p>Hidden content</p>
      </FilterPanel>,
    );
    expect(screen.queryByText('Hidden content')).not.toBeInTheDocument();
  });

  it('collapses when the toggle button is clicked', async () => {
    render(
      <FilterPanel title="Tags">
        <p>Tag filters here</p>
      </FilterPanel>,
    );
    expect(screen.getByText('Tag filters here')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button'));
    expect(screen.queryByText('Tag filters here')).not.toBeInTheDocument();
  });

  it('expands again after a second click on the toggle button', async () => {
    render(
      <FilterPanel title="Tags">
        <p>Tag filters here</p>
      </FilterPanel>,
    );
    const toggle = screen.getByRole('button');
    await userEvent.click(toggle); // collapse
    expect(screen.queryByText('Tag filters here')).not.toBeInTheDocument();
    await userEvent.click(toggle); // expand
    expect(screen.getByText('Tag filters here')).toBeInTheDocument();
  });

  it('sets aria-expanded to true on the toggle button when expanded', () => {
    render(
      <FilterPanel title="Filters">
        <p>Content</p>
      </FilterPanel>,
    );
    expect(screen.getByRole('button')).toHaveAttribute('aria-expanded', 'true');
  });

  it('sets aria-expanded to false on the toggle button when collapsed', async () => {
    render(
      <FilterPanel title="Filters">
        <p>Content</p>
      </FilterPanel>,
    );
    await userEvent.click(screen.getByRole('button'));
    expect(screen.getByRole('button')).toHaveAttribute('aria-expanded', 'false');
  });

  it('is keyboard operable — toggles with Enter key', async () => {
    render(
      <FilterPanel title="Filters">
        <p>Content</p>
      </FilterPanel>,
    );
    const toggle = screen.getByRole('button');
    toggle.focus();
    await userEvent.keyboard('{Enter}');
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
  });

  it('is keyboard operable — toggles with Space key', async () => {
    render(
      <FilterPanel title="Filters">
        <p>Content</p>
      </FilterPanel>,
    );
    const toggle = screen.getByRole('button');
    toggle.focus();
    await userEvent.keyboard(' ');
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
  });
});
