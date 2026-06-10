import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SecretField } from './SecretField';

// The real server mask — matches SECRET_MASK in settings_routes.py.
const MASK = '********';

describe('SecretField', () => {
  it('shows the masked value and a Replace action initially', () => {
    render(
      <SecretField id="tok" label="API token" maskedValue={MASK} onChange={() => {}} />,
    );
    expect(screen.getByLabelText('API token')).toHaveValue(MASK);
    expect(screen.getByRole('button', { name: /replace/i })).toBeInTheDocument();
  });

  it('the masked field is read-only before Replace is clicked', async () => {
    const onChange = vi.fn();
    render(
      <SecretField id="tok" label="API token" maskedValue={MASK} onChange={onChange} />,
    );
    await userEvent.type(screen.getByLabelText('API token'), 'x');
    expect(onChange).not.toHaveBeenCalled();
  });

  it('does not show a reveal toggle while masked', () => {
    render(
      <SecretField id="tok" label="API token" maskedValue={MASK} onChange={() => {}} />,
    );
    expect(screen.queryByRole('button', { name: /reveal|hide/i })).not.toBeInTheDocument();
  });

  it('clicking Replace clears the field and makes it editable', async () => {
    render(
      <SecretField id="tok" label="API token" maskedValue={MASK} onChange={() => {}} />,
    );
    await userEvent.click(screen.getByRole('button', { name: /replace/i }));
    expect(screen.getByLabelText('API token')).toHaveValue('');
    expect(screen.getByLabelText('API token')).not.toHaveAttribute('readonly');
  });

  it('reports typed characters via onChange once replacing', async () => {
    const onChange = vi.fn();
    render(
      <SecretField id="tok" label="API token" maskedValue={MASK} onChange={onChange} />,
    );
    await userEvent.click(screen.getByRole('button', { name: /replace/i }));
    await userEvent.type(screen.getByLabelText('API token'), 's');
    expect(onChange).toHaveBeenCalledWith('s');
  });

  it('the field is type=password while replacing, before reveal', async () => {
    render(
      <SecretField id="tok" label="API token" maskedValue={MASK} onChange={() => {}} />,
    );
    await userEvent.click(screen.getByRole('button', { name: /replace/i }));
    expect(screen.getByLabelText('API token')).toHaveAttribute('type', 'password');
  });

  it('the reveal toggle flips the field to type=text', async () => {
    render(
      <SecretField id="tok" label="API token" maskedValue={MASK} onChange={() => {}} />,
    );
    await userEvent.click(screen.getByRole('button', { name: /replace/i }));
    await userEvent.click(screen.getByRole('button', { name: /reveal/i }));
    expect(screen.getByLabelText('API token')).toHaveAttribute('type', 'text');
  });

  it('a Cancel action returns the field to the masked, locked state', async () => {
    const onChange = vi.fn();
    render(
      <SecretField id="tok" label="API token" maskedValue={MASK} onChange={onChange} />,
    );
    await userEvent.click(screen.getByRole('button', { name: /replace/i }));
    await userEvent.type(screen.getByLabelText('API token'), 'abc');
    await userEvent.click(screen.getByRole('button', { name: /cancel/i }));
    expect(screen.getByLabelText('API token')).toHaveValue(MASK);
    // Cancelling reverts the key to "unchanged" — onChange is called with null.
    expect(onChange).toHaveBeenLastCalledWith(null);
  });

  it('forwards a custom className', () => {
    const { container } = render(
      <SecretField
        id="tok"
        label="API token"
        maskedValue={MASK}
        onChange={() => {}}
        className="extra"
      />,
    );
    expect(container.firstElementChild?.className).toContain('extra');
  });
});
