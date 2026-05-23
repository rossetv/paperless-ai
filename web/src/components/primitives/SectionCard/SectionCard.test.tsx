import { render, screen } from '@testing-library/react';
import { SectionCard } from './SectionCard';

describe('SectionCard', () => {
  it('renders the title as a level-2 heading', () => {
    render(
      <SectionCard title="LLM Provider">
        <p>body</p>
      </SectionCard>,
    );
    expect(
      screen.getByRole('heading', { level: 2, name: 'LLM Provider' }),
    ).toBeInTheDocument();
  });

  it('renders the subtitle when given', () => {
    render(
      <SectionCard title="OCR" subtitle="Vision-model transcription.">
        <p>body</p>
      </SectionCard>,
    );
    expect(screen.getByText('Vision-model transcription.')).toBeInTheDocument();
  });

  it('renders the children body', () => {
    render(
      <SectionCard title="OCR">
        <p>OCR rows here</p>
      </SectionCard>,
    );
    expect(screen.getByText('OCR rows here')).toBeInTheDocument();
  });

  it('renders the icon slot', () => {
    render(
      <SectionCard title="OCR" icon={<svg data-testid="icon" />}>
        <p>body</p>
      </SectionCard>,
    );
    expect(screen.getByTestId('icon')).toBeInTheDocument();
  });

  it('renders the badge slot', () => {
    render(
      <SectionCard title="Paperless" badge={<span>Connected</span>}>
        <p>body</p>
      </SectionCard>,
    );
    expect(screen.getByText('Connected')).toBeInTheDocument();
  });

  it('exposes a region landmark named by the title for in-page navigation', () => {
    render(
      <SectionCard title="LLM Provider" id="llm">
        <p>body</p>
      </SectionCard>,
    );
    const region = screen.getByRole('region', { name: 'LLM Provider' });
    expect(region).toHaveAttribute('id', 'llm');
  });

  it('forwards a custom className', () => {
    const { container } = render(
      <SectionCard title="OCR" className="extra">
        <p>body</p>
      </SectionCard>,
    );
    expect(container.firstElementChild?.className).toContain('extra');
  });
});
