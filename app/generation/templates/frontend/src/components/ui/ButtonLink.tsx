import { Link, type LinkProps } from 'react-router-dom';
import { cn } from '../../lib/cn';

type Variant = 'primary' | 'secondary';

const variants: Record<Variant, string> = {
  primary: 'bg-primary text-onPrimary hover:bg-primaryHover border border-transparent',
  secondary: 'bg-surface text-text border border-borderStrong hover:bg-surfaceMuted',
};

/* A link that looks like a Button: navigation is a link (semantics), not a click handler. */
export function ButtonLink({ variant = 'primary', className, ...rest }: LinkProps & { variant?: Variant }) {
  return (
    <Link
      className={cn(
        'inline-flex min-h-[44px] items-center justify-center gap-2 rounded-md px-4 text-sm font-medium no-underline transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focusRing md:min-h-[40px]',
        variants[variant],
        className,
      )}
      {...rest}
    />
  );
}
