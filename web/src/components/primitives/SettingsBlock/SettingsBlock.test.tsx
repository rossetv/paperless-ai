import { render, screen } from '@testing-library/react';
import { SettingsBlock } from './SettingsBlock';

describe('SettingsBlock', () => {
  it('renders the title as a level-2 heading', () => {
    render(
      <SettingsBlock title="LLM Provider">
        <p>body</p>
      </SettingsBlock>,
    );
    expect(screen.getByRole('heading', { level: 2, name: 'LLM Provider' })).toBeInTheDocument();
  });

  it('renders the subtitle when given', () => {
    render(
      <SettingsBlock title="OCR" subtitle="Vision-model transcription.">
        <p>body</p>
      </SettingsBlock>,
    );
    expect(screen.getByText('Vision-model transcription.')).toBeInTheDocument();
  });

  it('does not render a subtitle when none is given', () => {
    const { container } = render(
      <SettingsBlock title="OCR">
        <p>body</p>
      </SettingsBlock>,
    );
    // The only <p> should be the body content.
    expect(container.querySelector('p')?.textContent).toBe('body');
  });

  it('renders children in the body', () => {
    render(
      <SettingsBlock title="Logging">
        <p>cards here</p>
      </SettingsBlock>,
    );
    expect(screen.getByText('cards here')).toBeInTheDocument();
  });

  it('sets the id on the root and exposes a region landmark', () => {
    render(
      <SettingsBlock title="LLM Provider" id="llm">
        <p>body</p>
      </SettingsBlock>,
    );
    const region = screen.getByRole('region', { name: 'LLM Provider' });
    expect(region).toHaveAttribute('id', 'llm');
  });

  it('forwards a custom className to the root', () => {
    const { container } = render(
      <SettingsBlock title="OCR" className="extra">
        <p>body</p>
      </SettingsBlock>,
    );
    expect(container.firstElementChild?.className).toContain('extra');
  });
});
