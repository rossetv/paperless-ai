import { render, screen } from '@testing-library/react';
import { Card } from './Card';

describe('Card', () => {
  it('renders its children', () => {
    render(<Card>Card content</Card>);
    expect(screen.getByText('Card content')).toBeInTheDocument();
  });

  it('renders a <div> element by default', () => {
    const { container } = render(<Card>Content</Card>);
    expect((container.firstChild as Element).tagName).toBe('DIV');
  });

  it('renders as an <article> when as="article" is set', () => {
    const { container } = render(<Card as="article">Article content</Card>);
    expect((container.firstChild as Element).tagName).toBe('ARTICLE');
  });

  it('renders as a <section> when as="section" is set', () => {
    const { container } = render(<Card as="section">Section content</Card>);
    expect((container.firstChild as Element).tagName).toBe('SECTION');
  });

  it('applies the base card class', () => {
    const { container } = render(<Card>Content</Card>);
    expect((container.firstChild as Element).className).toMatch(/card/);
  });

  it('applies the elevated class when elevated is true', () => {
    const { container } = render(<Card elevated>Content</Card>);
    expect((container.firstChild as Element).className).toMatch(/elevated/);
  });

  it('does not apply the elevated class by default', () => {
    const { container } = render(<Card>Content</Card>);
    expect((container.firstChild as Element).className).not.toMatch(/elevated/);
  });

  it('applies the dark surface class when surface is dark', () => {
    const { container } = render(<Card surface="dark">Content</Card>);
    expect((container.firstChild as Element).className).toMatch(/dark/);
  });

  it('forwards a custom className', () => {
    const { container } = render(<Card className="my-card">Content</Card>);
    expect((container.firstChild as Element).className).toContain('my-card');
  });

  it('renders complex children', () => {
    render(
      <Card>
        <h2>Title</h2>
        <p>Body text</p>
      </Card>,
    );
    expect(screen.getByRole('heading', { name: 'Title' })).toBeInTheDocument();
    expect(screen.getByText('Body text')).toBeInTheDocument();
  });
});
