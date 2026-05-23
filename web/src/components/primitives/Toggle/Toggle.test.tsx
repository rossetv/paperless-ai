import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Toggle } from './Toggle';

describe('Toggle', () => {
  it('renders a switch with the on/off state', () => {
    render(<Toggle checked={false} onChange={() => {}} label="Verbose logging" />);
    const sw = screen.getByRole('switch', { name: 'Verbose logging' });
    expect(sw).toHaveAttribute('aria-checked', 'false');
  });

  it('reports aria-checked true when on', () => {
    render(<Toggle checked onChange={() => {}} label="Verbose logging" />);
    expect(screen.getByRole('switch')).toHaveAttribute('aria-checked', 'true');
  });

  it('calls onChange with the toggled value on click', async () => {
    const onChange = vi.fn();
    render(<Toggle checked={false} onChange={onChange} label="Verbose logging" />);
    await userEvent.click(screen.getByRole('switch'));
    expect(onChange).toHaveBeenCalledWith(true);
  });

  it('calls onChange with false when switching off', async () => {
    const onChange = vi.fn();
    render(<Toggle checked onChange={onChange} label="Verbose logging" />);
    await userEvent.click(screen.getByRole('switch'));
    expect(onChange).toHaveBeenCalledWith(false);
  });

  it('does not call onChange when disabled', async () => {
    const onChange = vi.fn();
    render(<Toggle checked={false} onChange={onChange} label="L" disabled />);
    await userEvent.click(screen.getByRole('switch'));
    expect(onChange).not.toHaveBeenCalled();
  });

  it('toggles on the Space key for keyboard users', async () => {
    const onChange = vi.fn();
    render(<Toggle checked={false} onChange={onChange} label="L" />);
    screen.getByRole('switch').focus();
    await userEvent.keyboard(' ');
    expect(onChange).toHaveBeenCalledWith(true);
  });

  it('forwards a custom className', () => {
    render(<Toggle checked={false} onChange={() => {}} label="L" className="extra" />);
    expect(screen.getByRole('switch').className).toContain('extra');
  });
});
