import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { IconButton } from './IconButton';

/** Minimal SVG icon stub for testing purposes. */
function SearchIcon(): React.ReactElement {
  return <svg data-testid="icon" aria-hidden="true" />;
}

describe('IconButton', () => {
  it('renders a button with an accessible aria-label', () => {
    render(
      <IconButton label="Search documents">
        <SearchIcon />
      </IconButton>,
    );
    expect(screen.getByRole('button', { name: 'Search documents' })).toBeInTheDocument();
  });

  it('renders the icon child inside the button', () => {
    render(
      <IconButton label="Close">
        <SearchIcon />
      </IconButton>,
    );
    expect(screen.getByTestId('icon')).toBeInTheDocument();
  });

  it('has aria-label matching the label prop', () => {
    render(
      <IconButton label="Toggle filter">
        <SearchIcon />
      </IconButton>,
    );
    expect(screen.getByRole('button')).toHaveAttribute('aria-label', 'Toggle filter');
  });

  it('fires onClick when clicked', async () => {
    const handleClick = vi.fn();
    render(
      <IconButton label="Activate" onClick={handleClick}>
        <SearchIcon />
      </IconButton>,
    );
    await userEvent.click(screen.getByRole('button'));
    expect(handleClick).toHaveBeenCalledTimes(1);
  });

  it('fires onClick when activated with Enter key', async () => {
    const handleClick = vi.fn();
    render(
      <IconButton label="Enter activate" onClick={handleClick}>
        <SearchIcon />
      </IconButton>,
    );
    screen.getByRole('button').focus();
    await userEvent.keyboard('{Enter}');
    expect(handleClick).toHaveBeenCalledTimes(1);
  });

  it('fires onClick when activated with Space key', async () => {
    const handleClick = vi.fn();
    render(
      <IconButton label="Space activate" onClick={handleClick}>
        <SearchIcon />
      </IconButton>,
    );
    screen.getByRole('button').focus();
    await userEvent.keyboard(' ');
    expect(handleClick).toHaveBeenCalledTimes(1);
  });

  it('does not fire onClick when disabled', async () => {
    const handleClick = vi.fn();
    render(
      <IconButton label="Disabled" disabled onClick={handleClick}>
        <SearchIcon />
      </IconButton>,
    );
    await userEvent.click(screen.getByRole('button'));
    expect(handleClick).not.toHaveBeenCalled();
  });

  it('is disabled when disabled prop is true', () => {
    render(
      <IconButton label="Disabled" disabled>
        <SearchIcon />
      </IconButton>,
    );
    expect(screen.getByRole('button')).toBeDisabled();
  });

  it('renders a native <button> element', () => {
    render(
      <IconButton label="Button element">
        <SearchIcon />
      </IconButton>,
    );
    expect(screen.getByRole('button').tagName).toBe('BUTTON');
  });

  it('applies a custom className', () => {
    render(
      <IconButton label="Custom class" className="my-custom">
        <SearchIcon />
      </IconButton>,
    );
    expect(screen.getByRole('button').className).toContain('my-custom');
  });
});
