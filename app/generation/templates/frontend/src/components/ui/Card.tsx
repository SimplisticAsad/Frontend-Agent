import type { HTMLAttributes, ReactNode } from 'react';
import { cn } from '../../lib/cn';

interface CardProps extends Omit<HTMLAttributes<HTMLElement>, 'title'> {
  title?: ReactNode;
  actions?: ReactNode;
}

export function Card({ title, actions, className, children, ...rest }: CardProps) {
  return (
    <section className={cn('rounded-lg border border-border bg-surface shadow-card', className)} {...rest}>
      {(title || actions) && (
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-3 sm:px-6">
          {title && <h2 className="text-lg font-semibold text-text">{title}</h2>}
          {actions}
        </div>
      )}
      <div className="p-4 sm:p-6">{children}</div>
    </section>
  );
}
