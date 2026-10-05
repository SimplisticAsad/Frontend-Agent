import { useState } from 'react';
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { APP_NAME, NAV_ITEMS } from '../app/navigation';
import { LOGIN_ROUTE } from '../app/routes';
import { Badge } from '../components/ui/Badge';
import { Button } from '../components/ui/Button';
import { useAuth } from '../features/auth/AuthContext';
import { usePermissions } from '../hooks/usePermissions';
import { cn } from '../lib/cn';

export function AppLayout() {
  const { user, signOut } = useAuth();
  const { can } = usePermissions();
  const navigate = useNavigate();
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
  const [lastPath, setLastPath] = useState(location.pathname);
  if (lastPath !== location.pathname) {
    setLastPath(location.pathname);
    setMenuOpen(false);
  }

  const items = NAV_ITEMS.filter((i) => i.permissions.every((p) => can(p)));
  const link = ({ isActive }: { isActive: boolean }) =>
    cn(
      'flex min-h-[44px] items-center rounded-md px-3 text-sm font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-focusRing md:min-h-[40px]',
      isActive ? 'bg-primary text-onPrimary' : 'text-text hover:bg-surfaceMuted',
    );

  return (
    <div className="min-h-screen bg-background md:flex">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-surface focus:px-3 focus:py-2">
        Skip to content
      </a>
      <aside className="hidden w-60 shrink-0 flex-col border-r border-border bg-surface md:flex">
        <div className="px-5 py-5 text-lg font-bold text-primary">{APP_NAME}</div>
        <nav aria-label="Primary" className="flex flex-col gap-1 px-3">
          {items.map((i) => (
            <NavLink key={i.to} to={i.to} className={link}>
              {i.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between gap-3 border-b border-border bg-surface px-4 py-2 sm:px-6">
          <button
            type="button"
            className="inline-flex min-h-[44px] min-w-[44px] items-center justify-center rounded-md border border-borderStrong text-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-focusRing md:hidden"
            aria-expanded={menuOpen}
            aria-controls="mobile-nav"
            aria-label="Menu"
            onClick={() => setMenuOpen((o) => !o)}
          >
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <path d="M3 5h14M3 10h14M3 15h14" strokeLinecap="round" />
            </svg>
          </button>
          <span className="whitespace-nowrap font-bold text-primary md:hidden">{APP_NAME}</span>
          <div className="ml-auto flex items-center gap-3">
            <span className="hidden text-sm text-text sm:inline" data-testid="current-user">
              {user?.name}
            </span>
            {user && (
              <span className="hidden sm:inline-flex">
                <Badge variant="info">{user.role}</Badge>
              </span>
            )}
            <Button
              variant="secondary"
              size="sm"
              onClick={() => {
                signOut();
                navigate(LOGIN_ROUTE, { replace: true });
              }}
            >
              Sign out
            </Button>
          </div>
        </header>
        {menuOpen && (
          <nav id="mobile-nav" aria-label="Primary mobile" className="flex flex-col gap-1 border-b border-border bg-surface p-3 md:hidden">
            {items.map((i) => (
              <NavLink key={i.to} to={i.to} className={link}>
                {i.label}
              </NavLink>
            ))}
          </nav>
        )}
        <main id="main" className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 sm:px-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
