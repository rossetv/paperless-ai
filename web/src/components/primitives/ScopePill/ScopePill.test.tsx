import { render, screen } from '@testing-library/react';
import { ScopePill } from './ScopePill';

describe('ScopePill', () => {
  it('renders the uppercase scope label', () => {
    render(<ScopePill scope="api" />);
    expect(screen.getByText('API')).toBeInTheDocument();
  });

  it('renders "MCP" for the mcp scope', () => {
    render(<ScopePill scope="mcp" />);
    expect(screen.getByText('MCP')).toBeInTheDocument();
  });

  it('renders "Admin" for the admin scope', () => {
    render(<ScopePill scope="admin" />);
    expect(screen.getByText('Admin')).toBeInTheDocument();
  });

  it('applies a scope-specific class', () => {
    render(<ScopePill scope="mcp" />);
    expect(screen.getByText('MCP').className).toMatch(/mcp/);
  });

  it('renders as a non-interactive <span>', () => {
    render(<ScopePill scope="api" />);
    expect(screen.getByText('API').tagName).toBe('SPAN');
  });

  it('forwards a custom className', () => {
    render(<ScopePill scope="api" className="extra" />);
    expect(screen.getByText('API').className).toContain('extra');
  });
});
