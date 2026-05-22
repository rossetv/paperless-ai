import { render, screen } from '@testing-library/react';
import { DocumentSnippet } from './DocumentSnippet';

describe('DocumentSnippet', () => {
  it('renders the snippet text', () => {
    render(<DocumentSnippet snippet="The boiler was installed in 2021." />);
    expect(
      screen.getByText(/The boiler was installed in 2021/),
    ).toBeInTheDocument();
  });

  it('highlights **bold** runs as marks', () => {
    const { container } = render(
      <DocumentSnippet snippet="A total of **£1,847.32** was paid." />,
    );
    expect(container.querySelectorAll('mark')).toHaveLength(1);
  });

  it('renders an accessible notice for an empty snippet', () => {
    render(<DocumentSnippet snippet="" />);
    expect(screen.getByText(/no excerpt available/i)).toBeInTheDocument();
  });
});
