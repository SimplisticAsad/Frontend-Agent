import type { ReactNode } from 'react';
import { cn } from '../../lib/cn';
import type { StatusVariant } from './Badge';

const styles: Record<StatusVariant, string> = {
  neutral: 'bg-status-neutral-bg text-status-neutral-fg border-status-neutral-border',
  info: 'bg-status-info-bg text-status-info-fg border-status-info-border',
  success: 'bg-status-success-bg text-status-success-fg border-status-success-border',
  warning: 'bg-status-warning-bg text-status-warning-fg border-status-warning-border',
  danger: 'bg-status-danger-bg text-status-danger-fg border-status-danger-border',
};

interface AlertProps {
  variant?: StatusVariant;
  title?: string;
  children?: ReactNode;
  className?: string;
  'data-testid'?: string;
}

export function Alert({ variant = 'info', title, children, className, ...rest }: AlertProps) {
  const urgent = variant === 'danger' || variant === 'warning';
  return (
    <div role={urgent ? 'alert' : 'status'} className={cn('rounded-md border px-4 py-3 text-sm', styles[variant], className)} {...rest}>
      {title && <p className="font-semibold">{title}</p>}
      {children && <div className={title ? 'mt-1' : undefined}>{children}</div>}
    </div>
  );
}
