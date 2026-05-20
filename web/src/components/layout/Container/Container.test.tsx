import { render, screen } from '@testing-library/react';
import { Container } from './Container';

describe('Container', () => {
  it('renders its children', () => {
    render(<Container>Container content</Container>);
    expect(screen.getByText('Container content')).toBeInTheDocument();
  });

  it('renders as a <div> element', () => {
    const { container } = render(<Container>Content</Container>);
    expect((container.firstChild as Element).tagName).toBe('DIV');
  });

  it('applies the base container class', () => {
    const { container } = render(<Container>Content</Container>);
    expect((container.firstChild as Element).className).toMatch(/container/);
  });

  it('forwards a custom className', () => {
    const { container } = render(<Container className="custom">Content</Container>);
    expect((container.firstChild as Element).className).toContain('custom');
  });

  it('renders complex children', () => {
    render(
      <Container>
        <h1>Title</h1>
        <p>Body text</p>
      </Container>,
    );
    expect(screen.getByRole('heading', { name: 'Title' })).toBeInTheDocument();
    expect(screen.getByText('Body text')).toBeInTheDocument();
  });
});
