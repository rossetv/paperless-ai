import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { SettingsLayout } from './SettingsLayout';

function renderLayout(props: Partial<Parameters<typeof SettingsLayout>[0]> = {}) {
  return render(
    <MemoryRouter initialEntries={['/settings/users']}>
      <SettingsLayout title="Users" {...props}>
        <p>Body content</p>
      </SettingsLayout>
    </MemoryRouter>,
  );
}

describe('SettingsLayout', () => {
  it('renders the page title as a level-1 heading', () => {
    renderLayout();
    expect(screen.getByRole('heading', { level: 1, name: 'Users' })).toBeInTheDocument();
  });

  it('renders the subtitle when given', () => {
    renderLayout({ subtitle: 'Manage who can sign in.' });
    expect(screen.getByText('Manage who can sign in.')).toBeInTheDocument();
  });

  it('does not render a subtitle paragraph when none is given', () => {
    const { container } = renderLayout();
    expect(container.querySelector('p')?.textContent).toBe('Body content');
  });

  it('renders the children in the content region', () => {
    renderLayout();
    expect(screen.getByText('Body content')).toBeInTheDocument();
  });

  it('renders the settings side-nav with the Access control group', () => {
    renderLayout();
    expect(screen.getByText('Access control')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Users' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'API Keys' })).toBeInTheDocument();
  });

  it('forwards a custom className to the root', () => {
    const { container } = renderLayout({ className: 'extra' });
    expect(container.firstElementChild?.className).toContain('extra');
  });

  it('renders the Pipeline nav group with the five pipeline section links', () => {
    renderLayout();
    expect(screen.getByText('Pipeline')).toBeInTheDocument();
    // No "AI providers" item — provider choice lives on each step's card now.
    const pipelineItems = ['Connections', 'OCR', 'Classification', 'Indexing', 'Search'];
    for (const name of pipelineItems) {
      expect(screen.getByRole('link', { name })).toBeInTheDocument();
    }
    expect(screen.queryByRole('link', { name: 'AI providers' })).toBeNull();
  });

  it('renders the Operations nav group', () => {
    renderLayout();
    expect(screen.getByText('Operations')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Automation & Daemons' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Logging' })).toBeInTheDocument();
  });

  it('points the Connections link at the correct settings anchor', () => {
    renderLayout();
    expect(screen.getByRole('link', { name: 'Connections' })).toHaveAttribute(
      'href',
      '/settings#connections',
    );
  });

  it('points the Classification link at the correct settings anchor', () => {
    renderLayout();
    expect(screen.getByRole('link', { name: 'Classification' })).toHaveAttribute(
      'href',
      '/settings#classification',
    );
  });

  it('points the Indexing link at the correct settings anchor', () => {
    renderLayout();
    expect(screen.getByRole('link', { name: 'Indexing' })).toHaveAttribute(
      'href',
      '/settings#indexing',
    );
  });
});
