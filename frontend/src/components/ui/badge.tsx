import * as React from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '../../lib/utils';

const badgeVariants = cva(
  'inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2',
  {
    variants: {
      variant: {
        default: 'border-transparent bg-primary text-primary-foreground',
        secondary: 'border-transparent bg-secondary text-secondary-foreground',
        destructive: 'border-transparent bg-destructive text-destructive-foreground',
        outline: 'text-foreground',
        // Security levels
        public: 'border-emerald-200 bg-emerald-50 text-emerald-700 font-medium',
        internal: 'border-blue-200 bg-blue-50 text-blue-700 font-medium',
        confidential: 'border-amber-300 bg-amber-50 text-amber-800 font-semibold',
        restricted: 'border-rose-300 bg-rose-50 text-rose-800 font-bold tracking-wide',
        // Status
        ready: 'border-emerald-200 bg-emerald-50 text-emerald-700',
        processing: 'border-sky-200 bg-sky-50 text-sky-700 animate-pulse',
        quarantined: 'border-amber-200 bg-amber-50 text-amber-700',
        failed: 'border-rose-200 bg-rose-50 text-rose-700',
      },
    },
    defaultVariants: {
      variant: 'default',
    },
  }
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { Badge, badgeVariants };
