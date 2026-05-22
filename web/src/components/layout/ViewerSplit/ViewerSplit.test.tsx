import { render, screen } from '@testing-library/react';
import { ViewerSplit } from './ViewerSplit';

describe('ViewerSplit', () => {
  it('renders the main region', () => {
    render(
      <ViewerSplit sidebar={<aside>side</aside>}>
        <div>main</div>
      </ViewerSplit>,
    );
    expect(screen.getByText('main')).toBeInTheDocument();
  });

  it('renders the sidebar region', () => {
    render(
      <ViewerSplit sidebar={<aside>side</aside>}>
        <div>main</div>
      </ViewerSplit>,
    );
    expect(screen.getByText('side')).toBeInTheDocument();
  });

  it('merges a custom className', () => {
    const { container } = render(
      <ViewerSplit sidebar={<aside>s</aside>} className="extra">
        <div>m</div>
      </ViewerSplit>,
    );
    expect((container.firstChild as Element).className).toContain('extra');
  });
});
