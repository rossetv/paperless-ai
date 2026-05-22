import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { NoResultsScreen } from './NoResultsScreen';

vi.mock('../FilterControls/FilterControls', () => ({
  FilterControls: () => <div data-testid="mock-filter-controls" />,
}));

const EMPTY_FILTERS = {
  tag_ids: [],
  correspondent_id: null,
  document_type_id: null,
  date_from: null,
  date_to: null,
};

function renderScreen(overrides = {}) {
  return render(
    <NoResultsScreen
      query="payslip from 2019 with a bonus over £4000"
      filters={EMPTY_FILTERS}
      onFiltersChange={() => {}}
      onClearFilters={() => {}}
      onSearchWithoutFilters={() => {}}
      {...overrides}
    />,
  );
}

describe('NoResultsScreen', () => {
  it('recaps the query', () => {
    renderScreen();
    expect(
      screen.getByDisplayValue('payslip from 2019 with a bonus over £4000'),
    ).toBeInTheDocument();
  });

  it('renders the filter rail', () => {
    renderScreen();
    expect(screen.getByTestId('mock-filter-controls')).toBeInTheDocument();
  });

  it('states that no documents matched', () => {
    renderScreen();
    expect(screen.getByText(/no documents matched/i)).toBeInTheDocument();
  });

  it('fires onClearFilters when "Clear filters" is clicked', async () => {
    const onClearFilters = vi.fn();
    renderScreen({ onClearFilters });
    await userEvent.click(
      screen.getByRole('button', { name: /clear filters/i }),
    );
    expect(onClearFilters).toHaveBeenCalledTimes(1);
  });

  it('fires onSearchWithoutFilters when "Search without filters" is clicked', async () => {
    const onSearchWithoutFilters = vi.fn();
    renderScreen({ onSearchWithoutFilters });
    await userEvent.click(
      screen.getByRole('button', { name: /search without filters/i }),
    );
    expect(onSearchWithoutFilters).toHaveBeenCalledTimes(1);
  });
});
