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
import { validatePassword, validateUsername } from '../../../lib/credentials';
import type { User, UpdateUserRequest } from '../../../api/types';
import styles from './UserEditDrawer.module.css';

/** Selectable RBAC roles. */
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

/** The drawer's editable form state. */
interface FormState {
  username: string;
  displayName: string;
  email: string;
  role: RoleValue;
  password: string;
  confirm: string;
}

/** Build the initial form state from the user (or blank for create). */
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
 *
 * Tier: features/access (CODE_GUIDELINES §12.3). Allowed deps: components/*,
 * api/, hooks/, lib/.
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
  const [confirmingDelete, setConfirmingDelete] = React.useState(false);

  const createUser = useCreateUser();
  const updateUser = useUpdateUser();
  const deleteUser = useDeleteUser();

  /** Patch one form field and clear its pending error. */
  function setField<K extends keyof FormState>(key: K, value: FormState[K]): void {
    setForm((prev) => ({ ...prev, [key]: value }));
    setFieldError((prev) => ({ ...prev, [key]: undefined }));
  }

  /** Validate; returns an error map (empty when valid).
   *
   * The username and password rules are the canonical `validateUsername` /
   * `validatePassword` from the auth feature — the same checks the login and
   * first-run-setup screens use — so the three screens never drift. The
   * drawer adds only its own contextual gating: the username is validated on
   * create only (it is read-only in edit mode), a password is required on
   * create but optional on edit, and the confirm-field match is a
   * drawer-local concern the shared validators do not cover.
   */
  function validate(): Partial<Record<keyof FormState, string>> {
    const errors: Partial<Record<keyof FormState, string>> = {};
    if (isCreate) {
      const usernameError = validateUsername(form.username.trim());
      if (usernameError !== undefined) {
        errors.username = usernameError;
      }
    }
    // A password is required on create; optional on edit.
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

  /** Submit — create or update. */
  async function handleSubmit(event: React.FormEvent): Promise<void> {
    event.preventDefault();
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
    } catch {
      setServerError(
        isCreate
          ? 'Could not create the user. Check the details and try again.'
          : 'Could not save the changes. The server rejected the request.',
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

  /** Toggle the account's suspended / active status. */
  async function handleToggleStatus(): Promise<void> {
    if (user === null) return;
    setServerError(null);
    const next = user.status === 'active' ? 'suspended' : 'active';
    try {
      await updateUser.mutateAsync({ id: user.id, body: { status: next } });
      onClose();
    } catch {
      setServerError('Could not change the account status.');
    }
  }

  /** Delete the account (after the inline confirm step). */
  async function handleDelete(): Promise<void> {
    if (user === null) return;
    setServerError(null);
    try {
      await deleteUser.mutateAsync(user.id);
      onClose();
    } catch {
      setServerError(
        'Could not delete the account. The last admin cannot be removed.',
      );
      setConfirmingDelete(false);
    }
  }

  const title = isCreate
    ? 'Add user'
    : `Edit profile · ${user.display_name ?? user.username}`;
  const busy =
    createUser.isPending || updateUser.isPending || deleteUser.isPending;
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
            options={ROLE_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
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

        <div className={styles['footer']}>
          <div className={styles['destructive']}>
            {!isCreate && (
              <>
                <button
                  type="button"
                  className={styles['danger-button']}
                  disabled={isSelf || busy}
                  onClick={() => void handleToggleStatus()}
                >
                  {suspendLabel}
                </button>
                {confirmingDelete ? (
                  <button
                    type="button"
                    className={styles['danger-button']}
                    disabled={isSelf || busy}
                    onClick={() => void handleDelete()}
                  >
                    Confirm delete
                  </button>
                ) : (
                  <button
                    type="button"
                    className={styles['danger-button']}
                    disabled={isSelf || busy}
                    onClick={() => setConfirmingDelete(true)}
                  >
                    Delete account
                  </button>
                )}
              </>
            )}
          </div>
          <div className={styles['primary']}>
            <Button variant="secondary" type="button" onClick={onClose}>
              Cancel
            </Button>
            <Button variant="primary" type="submit" disabled={busy}>
              {isCreate ? 'Create user' : 'Save'}
            </Button>
          </div>
        </div>
      </form>
    </Modal>
  );
}
