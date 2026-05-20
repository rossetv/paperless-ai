import { render, screen } from '@testing-library/react';
import { DocumentSnippet } from './DocumentSnippet';

describe('DocumentSnippet', () => {
  it('renders the snippet text', () => {
    render(<DocumentSnippet snippet="The boiler warranty expires in 2026." />);
    expect(
      screen.getByText('The boiler warranty expires in 2026.'),
    ).toBeInTheDocument();
  });

  it('renders an empty snippet without crashing', () => {
    expect(() => render(<DocumentSnippet snippet="" />)).not.toThrow();
  });

  it('renders nothing visible when snippet is empty', () => {
    render(<DocumentSnippet snippet="" />);
    // The empty-state message should be present but the snippet text absent
    expect(screen.getByText(/no excerpt/i)).toBeInTheDocument();
  });

  it('renders the snippet in a readable paragraph element', () => {
    render(<DocumentSnippet snippet="Some excerpt text." />);
    const paragraph = document.querySelector('p');
    expect(paragraph).toBeInTheDocument();
    expect(paragraph).toHaveTextContent('Some excerpt text.');
  });
});
