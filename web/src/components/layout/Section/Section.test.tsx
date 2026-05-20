import { render, screen } from '@testing-library/react';
import { Section } from './Section';

describe('Section', () => {
  it('renders its children', () => {
    render(<Section>Section content</Section>);
    expect(screen.getByText('Section content')).toBeInTheDocument();
  });

  it('renders as a <section> element', () => {
    const { container } = render(<Section>Content</Section>);
    expect((container.firstChild as Element).tagName).toBe('SECTION');
  });

  it('applies the base section class', () => {
    const { container } = render(<Section>Content</Section>);
    expect((container.firstChild as Element).className).toMatch(/section/);
  });

  it('forwards a custom className', () => {
    const { container } = render(<Section className="custom">Content</Section>);
    expect((container.firstChild as Element).className).toContain('custom');
  });

  it('applies the spacious class when spacious prop is true', () => {
    const { container } = render(<Section spacious>Content</Section>);
    expect((container.firstChild as Element).className).toMatch(/spacious/);
  });

  it('does not apply the spacious class by default', () => {
    const { container } = render(<Section>Content</Section>);
    expect((container.firstChild as Element).className).not.toMatch(/spacious/);
  });

  it('renders complex children', () => {
    render(
      <Section>
        <h2>Section heading</h2>
        <p>Section body</p>
      </Section>,
    );
    expect(screen.getByRole('heading', { name: 'Section heading' })).toBeInTheDocument();
    expect(screen.getByText('Section body')).toBeInTheDocument();
  });
});
