import { render, screen } from '@testing-library/react';
import { Icon } from './Icon';

describe('Icon', () => {
  it('renders an SVG element', () => {
    const { container } = render(<Icon name="search" />);
    expect(container.querySelector('svg')).toBeInTheDocument();
  });

  it('is aria-hidden by default (decorative)', () => {
    const { container } = render(<Icon name="search" />);
    const svg = container.querySelector('svg');
    expect(svg).toHaveAttribute('aria-hidden', 'true');
  });

  it('sets aria-hidden="true" when label is not provided', () => {
    const { container } = render(<Icon name="close" />);
    expect(container.querySelector('svg')).toHaveAttribute('aria-hidden', 'true');
  });

  it('provides an accessible label when label prop is given', () => {
    render(<Icon name="search" label="Search" />);
    // When labelled, the SVG has role="img" and aria-label
    const svg = screen.getByRole('img', { name: 'Search' });
    expect(svg).toBeInTheDocument();
    expect(svg).not.toHaveAttribute('aria-hidden');
  });

  it('renders the correct icon for each supported name', () => {
    const names = [
      'search',
      'close',
      'document',
      'external-link',
      'chevron-down',
      'chevron-right',
      'filter',
      'info',
      'check',
      'warning',
      'arrow-left',
      'tag',
      'link',
      'sparkle',
      'waves',
      'eye',
      'paragraph',
      'lightning',
      'list-lines',
    ] as const;

    for (const name of names) {
      const { container, unmount } = render(<Icon name={name} />);
      expect(container.querySelector('svg')).toBeInTheDocument();
      unmount();
    }
  });

  it('applies the size-small class when size is "small"', () => {
    const { container } = render(<Icon name="search" size="small" />);
    const svg = container.querySelector('svg');
    // CSS Modules hash class names; check the className string contains 'small'
    expect(svg?.className.baseVal).toMatch(/small/);
  });

  it('applies the size-medium class by default', () => {
    const { container } = render(<Icon name="search" />);
    const svg = container.querySelector('svg');
    expect(svg?.className.baseVal).toMatch(/medium/);
  });

  it('applies the size-large class when size is "large"', () => {
    const { container } = render(<Icon name="search" size="large" />);
    const svg = container.querySelector('svg');
    expect(svg?.className.baseVal).toMatch(/large/);
  });

  it('forwards a custom className to the SVG', () => {
    const { container } = render(<Icon name="info" className="my-icon" />);
    expect(container.querySelector('svg')?.className.baseVal).toContain('my-icon');
  });
});
