import type { ReactNode } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { LOGIN_ROUTE } from '../../app/routes';
import { useAuth } from './AuthContext';

export function RequireAuth({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const location = useLocation();
  if (!user) return <Navigate to={LOGIN_ROUTE} replace state={{ from: location.pathname }} />;
  return <>{children}</>;
}
