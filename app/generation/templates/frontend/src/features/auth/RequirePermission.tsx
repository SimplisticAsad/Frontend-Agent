import type { ReactNode } from 'react';
import { usePermissions } from '../../hooks/usePermissions';
import type { PermissionId } from '../../lib/permissions';

/* UI-level gate only: the backend remains the authority for authorization. */
export function RequirePermission({ permissions, children }: { permissions: readonly PermissionId[]; children: ReactNode }) {
  const { can } = usePermissions();
  if (!permissions.every((p) => can(p))) {
    return (
      <div data-testid="access-denied" className="mx-auto max-w-lg rounded-lg border border-border bg-surface p-6 text-center">
        <h1 className="text-xl font-semibold text-text">Access denied</h1>
        <p className="mt-2 text-sm text-textMuted">Your role does not include access to this page.</p>
      </div>
    );
  }
  return <>{children}</>;
}
