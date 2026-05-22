import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Disclosure } from './Disclosure';

describe('Disclosure', () => {
  it('renders the summary content', () => {
    render(
      <Disclosure summary={<span>How this was built</span>}>
        <p>body</p>
      </Disclosure>,
    );
    expect(screen.getByText('How this was built')).toBeInTheDocument();
  });

  it('renders the body content', () => {
    render(
      <Disclosure summary={<span>Summary</span>}>
        <p>detail body</p>
      </Disclosure>,
    );
    expect(screen.getByText('detail body')).toBeInTheDocument();
  });

  it('is open by default when defaultOpen is set', () => {
    const { container } = render(
      <Disclosure summary={<span>Summary</span>} defaultOpen>
        <p>body</p>
      </Disclosure>,
    );
    expect(container.querySelector('details')).toHaveAttribute('open');
  });

  it('is closed by default when defaultOpen is not set', () => {
    const { container } = render(
      <Disclosure summary={<span>Summary</span>}>
        <p>body</p>
      </Disclosure>,
    );
    expect(container.querySelector('details')).not.toHaveAttribute('open');
  });

  it('toggles open when the summary is clicked', async () => {
    const { container } = render(
      <Disclosure summary={<span>Summary</span>}>
        <p>body</p>
      </Disclosure>,
    );
    const details = container.querySelector('details')!;
    expect(details).not.toHaveAttribute('open');
    await userEvent.click(screen.getByText('Summary'));
    expect(details).toHaveAttribute('open');
  });

  it('merges a custom className onto the details element', () => {
    const { container } = render(
      <Disclosure summary={<span>S</span>} className="extra">
        <p>body</p>
      </Disclosure>,
    );
    expect(container.querySelector('details')?.className).toContain('extra');
  });
});
