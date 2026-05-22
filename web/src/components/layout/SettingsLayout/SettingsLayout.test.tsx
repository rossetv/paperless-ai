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

  it('renders the header actions slot', () => {
    renderLayout({ actions: <button type="button">Add user</button> });
    expect(screen.getByRole('button', { name: 'Add user' })).toBeInTheDocument();
  });

  it('renders the settings side-nav with the Access Control group', () => {
    renderLayout();
    expect(screen.getByText('Access Control')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Users' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'API Keys' })).toBeInTheDocument();
  });

  it('forwards a custom className to the root', () => {
    const { container } = renderLayout({ className: 'extra' });
    expect(container.firstElementChild?.className).toContain('extra');
  });
});
