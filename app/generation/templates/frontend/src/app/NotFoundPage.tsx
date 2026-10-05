import { Link } from 'react-router-dom';
import { HOME_ROUTE } from './routes';

export function NotFoundPage() {
  return (
    <main className="mx-auto max-w-lg p-8 text-center" data-testid="page-not-found">
      <h1 className="text-2xl font-semibold text-text">Page not found</h1>
      <p className="mt-2 text-textMuted">The page you are looking for does not exist.</p>
      <Link className="mt-4 inline-block font-medium text-primary underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-focusRing" to={HOME_ROUTE}>
        Go to the start page
      </Link>
    </main>
  );
}
