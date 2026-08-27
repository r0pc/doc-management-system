import * as React from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '../../lib/utils';

const badgeVariants = cva(
  'inline-flex items-center rounded-full border px-2 py-0.2 text-[11px] font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2',
  {
    variants: {
      variant: {
        default: 'border-transparent bg-[#0969da] text-white dark:bg-[#1f6feb]',
        secondary: 'border-[#d0d7de] dark:border-[#30363d] bg-[#f6f8fa] dark:bg-[#21262d] text-[#1f2328] dark:text-[#e6edf3]',
        destructive: 'border-[#ff8182]/40 bg-[#ffebe9] dark:bg-[#da3633]/25 text-[#cf222e] dark:text-[#f85149]',
        outline: 'border-[#d0d7de] dark:border-[#30363d] text-[#1f2328] dark:text-[#e6edf3]',
        // GitHub-styled Security levels
        public: 'border-[#4ac26b]/40 bg-[#dafbe1] dark:bg-[#238636]/25 text-[#1a7f37] dark:text-[#3fb950] font-semibold',
        internal: 'border-[#54aeff]/40 bg-[#ddf4ff] dark:bg-[#388bfd]/20 text-[#0969da] dark:text-[#58a6ff] font-semibold',
        confidential: 'border-[#d4a72c]/40 bg-[#fff8c5] dark:bg-[#9e6a03]/30 text-[#9a6700] dark:text-[#d29922] font-semibold',
        restricted: 'border-[#ff8182]/40 bg-[#ffebe9] dark:bg-[#da3633]/30 text-[#cf222e] dark:text-[#f85149] font-bold tracking-wide',
        // Status
        ready: 'border-[#4ac26b]/40 bg-[#dafbe1] dark:bg-[#238636]/25 text-[#1a7f37] dark:text-[#3fb950]',
        processing: 'border-[#54aeff]/40 bg-[#ddf4ff] dark:bg-[#388bfd]/20 text-[#0969da] dark:text-[#58a6ff] animate-pulse',
        quarantined: 'border-[#d4a72c]/40 bg-[#fff8c5] dark:bg-[#9e6a03]/30 text-[#9a6700] dark:text-[#d29922]',
        failed: 'border-[#ff8182]/40 bg-[#ffebe9] dark:bg-[#da3633]/25 text-[#cf222e] dark:text-[#f85149]',
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
