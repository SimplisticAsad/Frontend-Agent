import { forwardRef, type ButtonHTMLAttributes } from 'react';
import { cn } from '../../lib/cn';
import { Spinner } from './Spinner';

export type ButtonVariant = 'primary' | 'secondary' | 'danger' | 'ghost';
export type ButtonSize = 'sm' | 'md';

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
}

const variants: Record<ButtonVariant, string> = {
  primary: 'bg-primary text-onPrimary hover:bg-primaryHover border border-transparent',
  secondary: 'bg-surface text-text border border-borderStrong hover:bg-surfaceMuted',
  danger: 'bg-danger text-onDanger hover:bg-dangerHover border border-transparent',
  ghost: 'bg-transparent text-text hover:bg-surfaceMuted border border-transparent',
};
const sizes: Record<ButtonSize, string> = {
  sm: 'min-h-[44px] px-3 text-sm md:min-h-[32px]',
  md: 'min-h-[44px] px-4 text-sm md:min-h-[40px]',
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'primary', size = 'md', loading = false, disabled, className, children, type = 'button', ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cn(
        'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focusRing disabled:cursor-not-allowed disabled:opacity-60',
        variants[variant],
        sizes[size],
        className,
      )}
      {...rest}
    >
      {loading && <Spinner className="h-4 w-4" label="" />}
      {children}
    </button>
  );
});
