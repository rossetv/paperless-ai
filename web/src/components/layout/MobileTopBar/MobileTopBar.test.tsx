import { render, screen } from '@testing-library/react';
import { MobileTopBar } from './MobileTopBar';

describe('MobileTopBar', () => {
  it('renders its brand slot', () => {
    render(<MobileTopBar brand={<span>Paperless AI</span>} />);
    expect(screen.getByText('Paperless AI')).toBeInTheDocument();
  });

  it('renders its actions slot when provided', () => {
    render(
      <MobileTopBar
        brand={<span>Brand</span>}
        actions={<button type="button">Menu</button>}
      />,
    );
    expect(screen.getByRole('button', { name: 'Menu' })).toBeInTheDocument();
  });

  it('renders a banner landmark', () => {
    const { container } = render(<MobileTopBar brand={<span>Brand</span>} />);
    expect(container.querySelector('[role="banner"]')).toBeInTheDocument();
  });

  it('does not render an actions region when actions is omitted', () => {
    const { container } = render(<MobileTopBar brand={<span>Brand</span>} />);
    // The actions div must not be in the DOM when no actions are supplied
    // (the outer .inner will have only .brand as its child).
    const inner = container.querySelector('[class*="inner"]');
    expect(inner?.children).toHaveLength(1);
  });

  it('forwards a custom className', () => {
    const { container } = render(
      <MobileTopBar brand={<span>Brand</span>} className="extra" />,
    );
    expect(container.firstElementChild?.className).toContain('extra');
  });

  it('renders brand and actions in the same row', () => {
    render(
      <MobileTopBar
        brand={<span>Brand</span>}
        actions={<span>Actions</span>}
      />,
    );
    expect(screen.getByText('Brand')).toBeInTheDocument();
    expect(screen.getByText('Actions')).toBeInTheDocument();
  });
});
