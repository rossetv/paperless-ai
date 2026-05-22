import { render, screen } from '@testing-library/react';
import { FormField } from './FormField';

/** A minimal control used to exercise the FormField wiring. */
function probeControl(id: string) {
  return ({ errorId, hasError }: { errorId: string | undefined; hasError: boolean }) => (
    <input
      id={id}
      aria-invalid={hasError ? 'true' : undefined}
      aria-describedby={errorId}
    />
  );
}

describe('FormField', () => {
  it('renders a visible label associated with the control', () => {
    render(
      <FormField id="email" label="Email address">
        {probeControl('email')}
      </FormField>,
    );
    const input = screen.getByLabelText('Email address');
    expect(input).toHaveAttribute('id', 'email');
    expect(screen.getByText('Email address').tagName).toBe('LABEL');
  });

  it('renders no label when the label prop is omitted', () => {
    render(<FormField id="nolabel">{probeControl('nolabel')}</FormField>);
    expect(document.querySelector('label')).not.toBeInTheDocument();
  });

  it('renders the error message when error is provided', () => {
    render(
      <FormField id="bad" label="Name" error="This field is required">
        {probeControl('bad')}
      </FormField>,
    );
    expect(screen.getByText('This field is required')).toBeInTheDocument();
  });

  it('gives the error message role="alert"', () => {
    render(
      <FormField id="bad" label="Name" error="Required">
        {probeControl('bad')}
      </FormField>,
    );
    expect(screen.getByRole('alert')).toHaveTextContent('Required');
  });

  it('passes hasError=true and an errorId to the control when in error', () => {
    render(
      <FormField id="bad" error="Required">
        {probeControl('bad')}
      </FormField>,
    );
    const input = screen.getByRole('textbox');
    expect(input).toHaveAttribute('aria-invalid', 'true');
    expect(input).toHaveAttribute('aria-describedby', 'bad-error');
  });

  it('passes hasError=false and no errorId when there is no error', () => {
    render(<FormField id="good">{probeControl('good')}</FormField>);
    const input = screen.getByRole('textbox');
    expect(input).not.toHaveAttribute('aria-invalid', 'true');
    expect(input).not.toHaveAttribute('aria-describedby');
  });

  it('treats an empty-string error as no error', () => {
    render(
      <FormField id="empty" error="">
        {probeControl('empty')}
      </FormField>,
    );
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('forwards a custom className onto the field wrapper', () => {
    const { container } = render(
      <FormField id="f" className="my-field">
        {probeControl('f')}
      </FormField>,
    );
    expect((container.firstChild as Element).className).toContain('my-field');
  });

  it('applies the dark surface class when surface="dark"', () => {
    const { container } = render(
      <FormField id="d" label="Username" surface="dark">
        {probeControl('d')}
      </FormField>,
    );
    expect((container.firstChild as Element).className).toMatch(/field-dark/);
  });

  it('does not apply the dark surface class by default', () => {
    const { container } = render(
      <FormField id="l" label="Username">
        {probeControl('l')}
      </FormField>,
    );
    expect((container.firstChild as Element).className).not.toMatch(/field-dark/);
  });
});
