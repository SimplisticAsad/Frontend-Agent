import { Outlet } from 'react-router-dom';
import { APP_NAME } from '../app/navigation';

export function PublicLayout() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-background px-4 py-8">
      <div className="mb-6 text-xl font-bold text-primary">{APP_NAME}</div>
      <main id="main" className="w-full max-w-md">
        <Outlet />
      </main>
    </div>
  );
}
