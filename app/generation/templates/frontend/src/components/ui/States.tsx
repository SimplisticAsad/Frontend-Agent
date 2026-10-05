import type { ReactNode } from 'react';
import { Button } from './Button';

export function Skeleton({ className = 'h-4 w-full' }: { className?: string }) {
  return <div aria-hidden="true" className={`animate-pulse rounded bg-surfaceMuted ${className}`} />;
}

export function LoadingState({ label = 'Loading…', rows = 4 }: { label?: string; rows?: number }) {
  return (
    <div data-testid="loading-state" role="status" aria-busy="true" className="flex flex-col gap-3 py-2">
      <span className="sr-only">{label}</span>
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className={i === 0 ? 'h-6 w-1/3' : 'h-10 w-full'} />
      ))}
    </div>
  );
}

export function EmptyState({ title, description, action }: { title: string; description?: string; action?: ReactNode }) {
  return (
    <div data-testid="empty-state" className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-borderStrong px-6 py-10 text-center">
      <h3 className="text-base font-semibold text-text">{title}</h3>
      {description && <p className="max-w-md text-sm text-textMuted">{description}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

export function ErrorState({ title = 'Something went wrong', message, onRetry }: { title?: string; message: string; onRetry?: () => void }) {
  return (
    <div data-testid="error-state" role="alert" className="flex flex-col items-start gap-3 rounded-lg border border-status-danger-border bg-status-danger-bg px-4 py-4 text-status-danger-fg sm:px-6">
      <div>
        <h3 className="font-semibold">{title}</h3>
        <p className="mt-1 text-sm">{message}</p>
      </div>
      {onRetry && (
        <Button variant="secondary" size="sm" onClick={onRetry}>
          Retry
        </Button>
      )}
    </div>
  );
}
