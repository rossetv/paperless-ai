import { render, screen } from '@testing-library/react';
import { Row } from './Row';

describe('Row', () => {
  it('renders the label', () => {
    render(<Row label="Server URL"><input /></Row>);
    expect(screen.getByText('Server URL')).toBeInTheDocument();
  });

  it('renders the control children', () => {
    render(
      <Row label="Server URL">
        <input data-testid="control" />
      </Row>,
    );
    expect(screen.getByTestId('control')).toBeInTheDocument();
  });

  it('renders the hint when given', () => {
    render(
      <Row label="Server URL" hint="Base URL of your Paperless instance.">
        <input />
      </Row>,
    );
    expect(screen.getByText('Base URL of your Paperless instance.')).toBeInTheDocument();
  });

  it('renders the env tag when given', () => {
    render(
      <Row label="Server URL" env="PAPERLESS_URL">
        <input />
      </Row>,
    );
    expect(screen.getByText('PAPERLESS_URL')).toBeInTheDocument();
  });

  it('associates the label with the control via htmlFor when controlId is given', () => {
    render(
      <Row label="Server URL" controlId="paperless-url">
        <input id="paperless-url" />
      </Row>,
    );
    // getByLabelText resolves only if <label for> points at the input id.
    expect(screen.getByLabelText('Server URL')).toBeInTheDocument();
  });

  it('renders the label as a plain span when no controlId is given', () => {
    const { container } = render(<Row label="Provider"><div /></Row>);
    expect(container.querySelector('label')).toBeNull();
  });

  it('applies the last modifier class when last is set', () => {
    const { container } = render(
      <Row label="X" last><input /></Row>,
    );
    expect(container.firstElementChild?.className).toMatch(/last/i);
  });

  it('forwards a custom className', () => {
    const { container } = render(
      <Row label="X" className="extra"><input /></Row>,
    );
    expect(container.firstElementChild?.className).toContain('extra');
  });

  it('shows the reindex pill when requiresReindex is true', () => {
    render(<Row label="Max Tokens" requiresReindex><input /></Row>);
    expect(
      screen.getByText(/rebuilds the index on save/i),
    ).toBeInTheDocument();
  });

  it('does not show the reindex pill when requiresReindex is false', () => {
    render(<Row label="Max Tokens"><input /></Row>);
    expect(
      screen.queryByText(/rebuilds the index on save/i),
    ).not.toBeInTheDocument();
  });
});
