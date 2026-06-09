import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { NumberStepper } from './NumberStepper';

describe('NumberStepper', () => {
  it('renders the current value in a spinbutton', () => {
    render(<NumberStepper value={10} onChange={() => {}} label="Top K" />);
    expect(screen.getByRole('spinbutton', { name: 'Top K' })).toHaveValue(10);
  });

  it('increments by one when + is pressed', async () => {
    const onChange = vi.fn();
    render(<NumberStepper value={10} onChange={onChange} label="Top K" />);
    await userEvent.click(screen.getByRole('button', { name: 'Increase Top K' }));
    expect(onChange).toHaveBeenCalledWith(11);
  });

  it('decrements by one when − is pressed', async () => {
    const onChange = vi.fn();
    render(<NumberStepper value={10} onChange={onChange} label="Top K" />);
    await userEvent.click(screen.getByRole('button', { name: 'Decrease Top K' }));
    expect(onChange).toHaveBeenCalledWith(9);
  });

  it('reports a typed number via onChange', async () => {
    const onChange = vi.fn();
    render(<NumberStepper value={10} onChange={onChange} label="Top K" />);
    const input = screen.getByRole('spinbutton', { name: 'Top K' });
    await userEvent.clear(input);
    await userEvent.type(input, '25');
    expect(onChange).toHaveBeenLastCalledWith(25);
  });

  it('does not decrement below the min', async () => {
    const onChange = vi.fn();
    render(<NumberStepper value={0} onChange={onChange} label="Top K" min={0} />);
    await userEvent.click(screen.getByRole('button', { name: 'Decrease Top K' }));
    expect(onChange).not.toHaveBeenCalled();
  });

  it('clamps a typed value below the min up to the min', async () => {
    const onChange = vi.fn();
    render(<NumberStepper value={5} onChange={onChange} label="Top K" min={1} />);
    const input = screen.getByRole('spinbutton', { name: 'Top K' });
    await userEvent.clear(input);
    await userEvent.type(input, '0');
    expect(onChange).toHaveBeenLastCalledWith(1);
  });

  it('passes a fractional step through to the spinbutton', () => {
    render(
      <NumberStepper value={0.6} onChange={() => {}} label="Floor" step={0.01} />,
    );
    expect(screen.getByRole('spinbutton', { name: 'Floor' })).toHaveAttribute(
      'step',
      '0.01',
    );
  });

  it('increments by a fractional step without IEEE-754 dust', async () => {
    const onChange = vi.fn();
    render(
      <NumberStepper value={0.69} onChange={onChange} label="Floor" step={0.01} max={1} />,
    );
    await userEvent.click(screen.getByRole('button', { name: 'Increase Floor' }));
    // 0.69 + 0.01 is 0.7000000000000001 in raw IEEE-754; the stepper snaps it.
    expect(onChange).toHaveBeenCalledWith(0.7);
  });

  it('decrements by a fractional step without IEEE-754 dust', async () => {
    const onChange = vi.fn();
    render(
      <NumberStepper value={0.3} onChange={onChange} label="Floor" step={0.01} min={0} />,
    );
    await userEvent.click(screen.getByRole('button', { name: 'Decrease Floor' }));
    // 0.3 − 0.01 is 0.29000000000000004 in raw IEEE-754; the stepper snaps it.
    expect(onChange).toHaveBeenCalledWith(0.29);
  });

  it('renders the unit suffix when given', () => {
    render(<NumberStepper value={300} onChange={() => {}} label="Interval" suffix="s" />);
    expect(screen.getByText('s')).toBeInTheDocument();
  });

  it('does not call onChange when disabled and + is clicked', async () => {
    const onChange = vi.fn();
    render(<NumberStepper value={10} onChange={onChange} label="Top K" disabled />);
    await userEvent.click(screen.getByRole('button', { name: 'Increase Top K' }));
    expect(onChange).not.toHaveBeenCalled();
  });

  it('forwards a custom className', () => {
    const { container } = render(
      <NumberStepper value={10} onChange={() => {}} label="Top K" className="extra" />,
    );
    expect(container.firstElementChild?.className).toContain('extra');
  });
});
