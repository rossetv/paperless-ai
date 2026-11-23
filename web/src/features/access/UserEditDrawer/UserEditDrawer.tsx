import React from 'react';
import { Modal } from '../../../components/patterns/Modal/Modal';
import { Select } from '../../../components/patterns/Select/Select';
import { Input } from '../../../components/primitives/Input/Input';
import { Button } from '../../../components/primitives/Button/Button';
import {
  useCreateUser,
  useUpdateUser,
  useDeleteUser,
} from '../../../api/hooks';
import { cn } from '../../../lib/cn';
import { errorDetail } from '../../../api/client';
import { validatePassword, validateUsername } from '../../../lib/credentials';
import type { User, UpdateUserRequest } from '../../../api/types';
import { useArmedConfirm } from '../useArmedConfirm';
import styles from './UserEditDrawer.module.css';

const ROLE_OPTIONS = [
  { value: 'admin', label: 'Admin' },
  { value: 'member', label: 'Member' },
  { value: 'readonly', label: 'Read-only' },
] as const;

type RoleValue = 'admin' | 'member' | 'readonly';

export interface UserEditDrawerProps {
  /** The user being edited, or `null` to create a new one. */
  user: User | null;
  /** True when `user` is the signed-in user — disables self-destructive actions. */
  isSelf: boolean;
  /** Called to dismiss the drawer (cancel, Escape, successful submit). */
  onClose: () => void;
}

interface FormState {
  username: string;
  displayName: string;
  email: string;
  role: RoleValue;
  password: string;
  confirm: string;
}

function initialState(user: User | null): FormState {
  return {
    username: user?.username ?? '',
    displayName: user?.display_name ?? '',
    email: user?.email ?? '',
    role: (user?.role as RoleValue | undefined) ?? 'member',
    password: '',
    confirm: '',
  };
}

/**
 * The create / edit user form, rendered inside the shared Modal.
 *
 * In create mode (`user === null`) every field is editable and a password is
 * required. In edit mode the username is read-only, the password is optional
 * ("leave empty to keep"), and suspend / delete actions appear. All three
 * destructive paths are disabled for one's own account (`isSelf`). The
 * last-admin guard is enforced server-side — a rejection is surfaced inline.
 */
export function UserEditDrawer({
  user,
  isSelf,
  onClose,
}: UserEditDrawerProps): React.ReactElement {
  const isCreate = user === null;
  const [form, setForm] = React.useState<FormState>(() => initialState(user));
  const [fieldError, setFieldError] = React.useState<Partial<Record<keyof FormState, string>>>({});
  const [serverError, setServerError] = React.useState<string | null>(null);
  const confirmDelete = useArmedConfirm<true>();

  const createUser = useCreateUser();
  const updateUser = useUpdateUser();
  const deleteUser = useDeleteUser();

  function setField<K extends keyof FormState>(key: K, value: FormState[K]): void {
    setForm((prev) => ({ ...prev, [key]: value }));
    setFieldError((prev) => ({ ...prev, [key]: undefined }));
  }

  /**
   * Uses the auth feature's `validateUsername` / `validatePassword` so this
   * form, login and first-run setup apply the same rules. Only the username
   * (create only), password-required (create only) and confirm-match gating
   * are local.
   */
  function validate(): Partial<Record<keyof FormState, string>> {
    const errors: Partial<Record<keyof FormState, string>> = {};
    if (isCreate) {
      const usernameError = validateUsername(form.username.trim());
      if (usernameError !== undefined) {
        errors.username = usernameError;
      }
    }
    const wantsPassword = isCreate || form.password.length > 0;
    if (wantsPassword) {
      const passwordError = validatePassword(form.password);
      if (passwordError !== undefined) {
        errors.password = passwordError;
      } else if (form.password !== form.confirm) {
        errors.confirm = 'Passwords do not match.';
      }
    }
    return errors;
  }

  async function handleSubmit(event: React.FormEvent): Promise<void> {
    event.preventDefault();
    if (busy) return;
    setServerError(null);
    const errors = validate();
    if (Object.keys(errors).length > 0) {
      setFieldError(errors);
      return;
    }
    try {
      if (isCreate) {
        await createUser.mutateAsync({
          username: form.username.trim(),
          password: form.password,
          display_name: form.displayName.trim() || null,
          email: form.email.trim() || null,
          role: form.role,
        });
      } else {
        await updateUser.mutateAsync({ id: user.id, body: changedFields() });
      }
      onClose();
    } catch (error) {
      setServerError(
        errorDetail(
          error,
          isCreate
            ? 'Could not create the user. Check the details and try again.'
            : 'Could not save the changes. The server rejected the request.',
        ),
      );
    }
  }

  /** In edit mode, build a patch of only the fields that changed. */
  function changedFields(): UpdateUserRequest {
    const body: UpdateUserRequest = {};
    if (user === null) return body;
    const displayName = form.displayName.trim() || null;
    const email = form.email.trim() || null;
    if (displayName !== (user.display_name ?? null)) body.display_name = displayName;
    if (email !== (user.email ?? null)) body.email = email;
    if (form.role !== user.role) body.role = form.role;
    if (form.password.length > 0) body.password = form.password;
    return body;
  }

  async function handleToggleStatus(): Promise<void> {
    if (user === null) return;
    setServerError(null);
    const next = user.status === 'active' ? 'suspended' : 'active';
    try {
      await updateUser.mutateAsync({ id: user.id, body: { status: next } });
      onClose();
    } catch (error) {
      setServerError(errorDetail(error, 'Could not change the account status.'));
    }
  }

  /** Delete the account (after the inline confirm step). */
  async function handleDelete(): Promise<void> {
    if (user === null) return;
    setServerError(null);
    try {
      await deleteUser.mutateAsync(user.id);
      onClose();
    } catch (error) {
      setServerError(
        errorDetail(
          error,
          'Could not delete the account. The last admin cannot be removed.',
        ),
      );
      confirmDelete.disarm();
    }
  }

  const title = isCreate
    ? 'Add user'
    : `Edit profile · ${user.display_name ?? user.username}`;
  const busy =
    createUser.isPending || updateUser.isPending || deleteUser.isPending;
  const selfHelpId = isSelf && !isCreate ? 'user-self-help' : undefined;
  const suspendLabel = user?.status === 'suspended' ? 'Reactivate' : 'Suspend';

  return (
    <Modal isOpen title={title} onClose={onClose}>
      <form onSubmit={handleSubmit} noValidate>
        <div className={styles['grid']}>
          <Input
            id="user-username"
            label="Username"
            value={form.username}
            disabled={!isCreate}
            error={fieldError.username}
            onChange={(e) => setField('username', e.target.value)}
          />
          <Input
            id="user-display-name"
            label="Display name"
            value={form.displayName}
            onChange={(e) => setField('displayName', e.target.value)}
          />
          <Input
            id="user-email"
            label="Email"
            type="email"
            value={form.email}
            onChange={(e) => setField('email', e.target.value)}
          />
          <Select
            id="user-role"
            label="Role"
            value={form.role}
            options={ROLE_OPTIONS}
            onChange={(value) => setField('role', value as RoleValue)}
          />
          <div className={styles['full']}>
            <div className={styles['grid']}>
              <Input
                id="user-password"
                label={isCreate ? 'New password' : 'New password (leave empty to keep)'}
                type="password"
                value={form.password}
                error={fieldError.password}
                onChange={(e) => setField('password', e.target.value)}
              />
              <Input
                id="user-confirm"
                label="Confirm password"
                type="password"
                value={form.confirm}
                error={fieldError.confirm}
                onChange={(e) => setField('confirm', e.target.value)}
              />
            </div>
          </div>
        </div>

        {serverError !== null && (
          <p className={styles['error']} role="alert">
            {serverError}
          </p>
        )}

        <div className={cn(styles['footer'], selfHelpId && styles['footer-self'])}>
          <div className={styles['actions']} {...confirmDelete.armedProps}>
            <div className={styles['destructive']} aria-busy={busy ? true : undefined}>
              {!isCreate && (
                <>
                  <Button
                    variant="ghost"
                    size="small"
                    type="button"
                    className={cn(busy && styles['pending-ghost'])}
                    aria-describedby={selfHelpId}
                    disabled={isSelf}
                    onClick={() => {
                      if (!busy) void handleToggleStatus();
                    }}
                  >
                    {suspendLabel}
                  </Button>
                  <span className={styles['destructive-separator']} aria-hidden="true" />
                  {confirmDelete.armed === true ? (
                    <Button
                      variant="destructive"
                      size="small"
                      type="button"
                      className={cn(busy && styles['pending'])}
                      aria-label={`Confirm delete ${user.username}`}
                      aria-describedby={selfHelpId}
                      disabled={isSelf}
                      onClick={() => {
                        // Not disabled while busy: a disabled button would drop keyboard focus.
                        if (confirmDelete.canConfirm() && !busy) void handleDelete();
                      }}
                    >
                      Confirm delete
                    </Button>
                  ) : (
                    <Button
                      variant="destructive"
                      size="small"
                      type="button"
                      aria-describedby={selfHelpId}
                      disabled={isSelf || busy}
                      onClick={() => confirmDelete.arm(true)}
                    >
                      Delete account
                    </Button>
                  )}
                </>
              )}
            </div>
            {isSelf && !isCreate && (
              <p id="user-self-help" className={styles['self-help']}>
                You can't suspend or delete your own account.
              </p>
            )}
          </div>
          <div className={styles['primary']} aria-busy={busy ? true : undefined}>
            <Button variant="secondary" type="button" onClick={onClose}>
              Cancel
            </Button>
            <Button
              variant="primary"
              type="submit"
              className={cn(busy && styles['pending-primary'])}
            >
              {isCreate ? 'Create user' : 'Save'}
            </Button>
          </div>
        </div>
      </form>
    </Modal>
  );
}
