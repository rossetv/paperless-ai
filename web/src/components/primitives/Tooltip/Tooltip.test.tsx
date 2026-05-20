import { render, screen, fireEvent } from '@testing-library/react';
import { Tooltip } from './Tooltip';

describe('Tooltip', () => {
  it('renders its child', () => {
    render(
      <Tooltip content="Helpful text">
        <button>Hover me</button>
      </Tooltip>,
    );
    expect(screen.getByRole('button', { name: 'Hover me' })).toBeInTheDocument();
  });

  it('does not show the tooltip content initially', () => {
    render(
      <Tooltip content="Hidden tip">
        <button>Trigger</button>
      </Tooltip>,
    );
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  });

  it('shows the tooltip on mouseenter', () => {
    render(
      <Tooltip content="Mouse tip">
        <button>Hover me</button>
      </Tooltip>,
    );
    fireEvent.mouseEnter(screen.getByRole('button'));
    expect(screen.getByRole('tooltip')).toBeInTheDocument();
    expect(screen.getByRole('tooltip')).toHaveTextContent('Mouse tip');
  });

  it('hides the tooltip on mouseleave', () => {
    render(
      <Tooltip content="Mouse tip">
        <button>Hover me</button>
      </Tooltip>,
    );
    const btn = screen.getByRole('button');
    fireEvent.mouseEnter(btn);
    expect(screen.getByRole('tooltip')).toBeInTheDocument();
    fireEvent.mouseLeave(btn);
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  });

  it('shows the tooltip on focus', () => {
    render(
      <Tooltip content="Focus tip">
        <button>Focusable</button>
      </Tooltip>,
    );
    // fireEvent.focus triggers synthetic React onFocus
    fireEvent.focus(screen.getByRole('button'));
    expect(screen.getByRole('tooltip')).toBeInTheDocument();
  });

  it('hides the tooltip on blur', () => {
    render(
      <Tooltip content="Focus tip">
        <button>Focusable</button>
      </Tooltip>,
    );
    const btn = screen.getByRole('button');
    fireEvent.focus(btn);
    expect(screen.getByRole('tooltip')).toBeInTheDocument();
    fireEvent.blur(btn);
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  });

  it('dismisses the tooltip with the Escape key', () => {
    render(
      <Tooltip content="Escape me">
        <button>Trigger</button>
      </Tooltip>,
    );
    const btn = screen.getByRole('button');
    fireEvent.focus(btn);
    expect(screen.getByRole('tooltip')).toBeInTheDocument();
    // fireEvent.keyDown targets the focused element directly
    fireEvent.keyDown(btn, { key: 'Escape' });
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  });

  it('wires aria-describedby on the trigger to the tooltip id', () => {
    render(
      <Tooltip content="Described">
        <button>Trigger</button>
      </Tooltip>,
    );
    const btn = screen.getByRole('button');
    fireEvent.mouseEnter(btn);
    const tooltip = screen.getByRole('tooltip');
    expect(btn).toHaveAttribute('aria-describedby', tooltip.id);
  });

  it('has role="tooltip" on the tooltip element', () => {
    render(
      <Tooltip content="Role check">
        <button>Trigger</button>
      </Tooltip>,
    );
    fireEvent.mouseEnter(screen.getByRole('button'));
    expect(screen.getByRole('tooltip')).toBeInTheDocument();
  });
});
