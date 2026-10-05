import type { HTMLAttributes, ReactNode, TdHTMLAttributes, ThHTMLAttributes } from 'react';
import { cn } from '../../lib/cn';

/* Below `md` rows become stacked cards (each cell shows its column label); from `md` up it is a regular table. */
export function Table({ className, children, ...rest }: HTMLAttributes<HTMLTableElement>) {
  return (
    <table role="table" className={cn('block w-full border-collapse text-left text-sm md:table', className)} {...rest}>
      {children}
    </table>
  );
}
export function THead({ children }: { children: ReactNode }) {
  return (
    <thead role="rowgroup" className="sr-only md:not-sr-only md:table-header-group">
      {children}
    </thead>
  );
}
export function TBody({ children }: { children: ReactNode }) {
  return (
    <tbody role="rowgroup" className="block md:table-row-group">
      {children}
    </tbody>
  );
}
export function Tr({ className, children, ...rest }: HTMLAttributes<HTMLTableRowElement>) {
  return (
    <tr
      role="row"
      className={cn('block rounded-lg border border-border bg-surface p-3 mb-3 md:mb-0 md:table-row md:rounded-none md:border-0 md:border-b md:p-0', className)}
      {...rest}
    >
      {children}
    </tr>
  );
}
export function Th({ className, children, ...rest }: ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th role="columnheader" scope="col" className={cn('px-4 py-3 text-xs font-semibold uppercase tracking-wide text-textMuted bg-surfaceMuted', className)} {...rest}>
      {children}
    </th>
  );
}
export function Td({ label, className, children, ...rest }: TdHTMLAttributes<HTMLTableCellElement> & { label?: string }) {
  return (
    <td
      role="cell"
      data-label={label}
      className={cn(
        'block py-1 text-text before:mb-0.5 before:block before:text-xs before:font-medium before:text-textMuted before:content-[attr(data-label)] md:table-cell md:px-4 md:py-3 md:align-middle md:before:hidden',
        className,
      )}
      {...rest}
    >
      {children}
    </td>
  );
}
