import type { ReactNode } from 'react';
import { cn } from '../../lib/cn';

export type StatusVariant = 'neutral' | 'info' | 'success' | 'warning' | 'danger';

const styles: Record<StatusVariant, string> = {
  neutral: 'bg-status-neutral-bg text-status-neutral-fg',
  info: 'bg-status-info-bg text-status-info-fg',
  success: 'bg-status-success-bg text-status-success-fg',
  warning: 'bg-status-warning-bg text-status-warning-fg',
  danger: 'bg-status-danger-bg text-status-danger-fg',
};

export function Badge({ variant = 'neutral', children, className }: { variant?: StatusVariant; children: ReactNode; className?: string }) {
  return <span className={cn('inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium', styles[variant], className)}>{children}</span>;
}
