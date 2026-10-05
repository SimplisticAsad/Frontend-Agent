import { useCallback } from 'react';
import { useAuth } from '../features/auth/AuthContext';
import { can as canDo, type PermissionId } from '../lib/permissions';

export function usePermissions() {
  const { user } = useAuth();
  const can = useCallback((permission: PermissionId, resource?: object | null) => canDo(user, permission, resource), [user]);
  return { can, user };
}
