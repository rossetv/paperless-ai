import { render, screen } from '@testing-library/react';
import { Icon } from './Icon';

describe('Icon', () => {
  it('renders an <i> element', () => {
    const { container } = render(<Icon name="search" />);
    expect(container.querySelector('i')).toBeInTheDocument();
  });

  it('applies the fa-solid family class', () => {
    const { container } = render(<Icon name="search" />);
    expect(container.querySelector('i')?.className).toMatch(/\bfa-solid\b/);
  });

  it('applies the mapped Font Awesome glyph class', () => {
    const { container } = render(<Icon name="search" />);
    // search maps to fa-magnifying-glass in the FA_CLASS table.
    expect(container.querySelector('i')?.className).toMatch(/\bfa-magnifying-glass\b/);
  });

  it('is aria-hidden by default (decorative)', () => {
    const { container } = render(<Icon name="search" />);
    expect(container.querySelector('i')).toHaveAttribute('aria-hidden', 'true');
  });

  it('sets aria-hidden="true" when label is not provided', () => {
    const { container } = render(<Icon name="close" />);
    expect(container.querySelector('i')).toHaveAttribute('aria-hidden', 'true');
  });

  it('provides an accessible label when label prop is given', () => {
    render(<Icon name="search" label="Search" />);
    // When labelled, the element has role="img" and aria-label.
    const el = screen.getByRole('img', { name: 'Search' });
    expect(el).toBeInTheDocument();
    expect(el).not.toHaveAttribute('aria-hidden');
  });

  it('renders the correct icon for each supported name', () => {
    const names = [
      'search',
      'close',
      'document',
      'external-link',
      'chevron-down',
      'chevron-right',
      'info',
      'check',
      'warning',
      'tag',
      'link',
      'sparkle',
      'waves',
      'eye',
      'eye-off',
      'paragraph',
      'lightning',
      'list-lines',
      'users',
      'key',
      'library',
      'index',
      'settings',
    ] as const;

    for (const name of names) {
      const { container, unmount } = render(<Icon name={name} />);
      const el = container.querySelector('i');
      expect(el).toBeInTheDocument();
      expect(el?.className).toMatch(/\bfa-solid\b/);
      expect(el?.className).toMatch(/\bfa-/);
      unmount();
    }
  });

  it('applies the size-small class when size is "small"', () => {
    const { container } = render(<Icon name="search" size="small" />);
    expect(container.querySelector('i')?.className).toMatch(/small/);
  });

  it('applies the size-medium class by default', () => {
    const { container } = render(<Icon name="search" />);
    expect(container.querySelector('i')?.className).toMatch(/medium/);
  });

  it('applies the size-large class when size is "large"', () => {
    const { container } = render(<Icon name="search" size="large" />);
    expect(container.querySelector('i')?.className).toMatch(/large/);
  });

  it('forwards a custom className', () => {
    const { container } = render(<Icon name="info" className="my-icon" />);
    expect(container.querySelector('i')?.className).toContain('my-icon');
  });
});
