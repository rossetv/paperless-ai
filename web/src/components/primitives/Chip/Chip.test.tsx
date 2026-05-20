import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Chip } from './Chip';

describe('Chip', () => {
  it('renders with its label text', () => {
    render(<Chip>Invoice</Chip>);
    expect(screen.getByText('Invoice')).toBeInTheDocument();
  });

  it('renders a <span> as the root element', () => {
    const { container } = render(<Chip>Tag</Chip>);
    expect(container.firstChild).not.toBeNull();
    // Root is a span, not a button
    expect((container.firstChild as Element).tagName).toBe('SPAN');
  });

  it('does not render a remove button when onRemove is not provided', () => {
    render(<Chip>Tag</Chip>);
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('renders a remove button when onRemove is provided', () => {
    render(<Chip onRemove={vi.fn()}>Tag</Chip>);
    expect(screen.getByRole('button')).toBeInTheDocument();
  });

  it('remove button has an accessible label', () => {
    render(<Chip onRemove={vi.fn()}>Invoice</Chip>);
    const removeBtn = screen.getByRole('button');
    // aria-label must name the action and the item
    expect(removeBtn).toHaveAttribute('aria-label', 'Remove Invoice');
  });

  it('accepts a custom removeLabel for the remove button', () => {
    render(<Chip onRemove={vi.fn()} removeLabel="Déselectionner Facture">Facture</Chip>);
    expect(screen.getByRole('button')).toHaveAttribute('aria-label', 'Déselectionner Facture');
  });

  it('fires onRemove when the remove button is clicked', async () => {
    const handleRemove = vi.fn();
    render(<Chip onRemove={handleRemove}>Tag</Chip>);
    await userEvent.click(screen.getByRole('button'));
    expect(handleRemove).toHaveBeenCalledTimes(1);
  });

  it('fires onRemove when the remove button is activated with Enter', async () => {
    const handleRemove = vi.fn();
    render(<Chip onRemove={handleRemove}>Tag</Chip>);
    screen.getByRole('button').focus();
    await userEvent.keyboard('{Enter}');
    expect(handleRemove).toHaveBeenCalledTimes(1);
  });

  it('fires onRemove when the remove button is activated with Space', async () => {
    const handleRemove = vi.fn();
    render(<Chip onRemove={handleRemove}>Tag</Chip>);
    screen.getByRole('button').focus();
    await userEvent.keyboard(' ');
    expect(handleRemove).toHaveBeenCalledTimes(1);
  });

  it('applies the selected class when selected is true', () => {
    const { container } = render(<Chip selected>Active</Chip>);
    expect((container.firstChild as Element).className).toMatch(/selected/);
  });

  it('does not apply the selected class by default', () => {
    const { container } = render(<Chip>Inactive</Chip>);
    expect((container.firstChild as Element).className).not.toMatch(/selected/);
  });

  it('forwards a custom className', () => {
    const { container } = render(<Chip className="my-chip">Label</Chip>);
    expect((container.firstChild as Element).className).toContain('my-chip');
  });
});
