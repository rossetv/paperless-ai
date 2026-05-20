import { render, screen } from '@testing-library/react';
import { Page } from './Page';

describe('Page', () => {
  it('renders its children', () => {
    render(<Page>Page content</Page>);
    expect(screen.getByText('Page content')).toBeInTheDocument();
  });

  it('renders as a <div> element', () => {
    const { container } = render(<Page>Content</Page>);
    expect((container.firstChild as Element).tagName).toBe('DIV');
  });

  it('applies the base page class', () => {
    const { container } = render(<Page>Content</Page>);
    expect((container.firstChild as Element).className).toMatch(/page/);
  });

  it('renders complex children', () => {
    render(
      <Page>
        <h1>Title</h1>
        <p>Body</p>
      </Page>,
    );
    expect(screen.getByRole('heading', { name: 'Title' })).toBeInTheDocument();
    expect(screen.getByText('Body')).toBeInTheDocument();
  });

  it('forwards a custom className', () => {
    const { container } = render(<Page className="custom">Content</Page>);
    expect((container.firstChild as Element).className).toContain('custom');
  });
});
