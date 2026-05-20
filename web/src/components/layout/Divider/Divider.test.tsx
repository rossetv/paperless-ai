import { render } from '@testing-library/react';
import { Divider } from './Divider';

describe('Divider', () => {
  it('renders an <hr> element', () => {
    const { container } = render(<Divider />);
    expect(container.querySelector('hr')).toBeInTheDocument();
  });

  it('applies the base divider class', () => {
    const { container } = render(<Divider />);
    expect((container.firstChild as Element).className).toMatch(/divider/);
  });

  it('applies the horizontal class by default', () => {
    const { container } = render(<Divider />);
    expect((container.firstChild as Element).className).toMatch(/horizontal/);
  });

  it('forwards a custom className', () => {
    const { container } = render(<Divider className="custom" />);
    expect((container.firstChild as Element).className).toContain('custom');
  });

  it('has role separator', () => {
    const { container } = render(<Divider />);
    // <hr> has implicit role="separator"
    expect(container.querySelector('hr')).toBeInTheDocument();
  });

  it('applies the decorative aria attribute when decorative is true', () => {
    const { container } = render(<Divider decorative />);
    expect((container.firstChild as Element).getAttribute('role')).toBe('presentation');
  });
});
