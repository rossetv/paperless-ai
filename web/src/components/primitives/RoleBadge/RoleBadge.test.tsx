import { render, screen } from '@testing-library/react';
import { RoleBadge } from './RoleBadge';

describe('RoleBadge', () => {
  it('renders the human-readable label for the admin role', () => {
    render(<RoleBadge role="admin" />);
    expect(screen.getByText('Admin')).toBeInTheDocument();
  });

  it('renders "Read-only" for the readonly role', () => {
    render(<RoleBadge role="readonly" />);
    expect(screen.getByText('Read-only')).toBeInTheDocument();
  });

  it('renders "Member" for the member role', () => {
    render(<RoleBadge role="member" />);
    expect(screen.getByText('Member')).toBeInTheDocument();
  });

  it('renders "Service" for the service role', () => {
    render(<RoleBadge role="service" />);
    expect(screen.getByText('Service')).toBeInTheDocument();
  });

  it('applies a role-specific class so each role is visually distinct', () => {
    render(<RoleBadge role="admin" />);
    expect(screen.getByText('Admin').className).toMatch(/admin/);
  });

  it('renders as a non-interactive <span>', () => {
    render(<RoleBadge role="member" />);
    expect(screen.getByText('Member').tagName).toBe('SPAN');
  });

  it('forwards a custom className', () => {
    render(<RoleBadge role="member" className="extra" />);
    expect(screen.getByText('Member').className).toContain('extra');
  });
});
