import * as React from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '../../lib/utils';

const buttonVariants = cva(
  'inline-flex items-center justify-center rounded-md text-xs font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50 disabled:pointer-events-none select-none',
  {
    variants: {
      variant: {
        default:
          'bg-[#1f883d] hover:bg-[#1a7f37] text-white dark:bg-[#238636] dark:hover:bg-[#2ea043] border border-[rgba(27,31,36,0.15)] dark:border-[rgba(240,246,252,0.1)] shadow-2xs',
        primary:
          'bg-[#0969da] hover:bg-[#0860ca] text-white dark:bg-[#1f6feb] dark:hover:bg-[#388bfd] border border-[rgba(27,31,36,0.15)] shadow-2xs',
        destructive:
          'bg-[#f6f8fa] hover:bg-[#cf222e] hover:text-white text-[#cf222e] dark:bg-[#21262d] dark:text-[#f85149] dark:hover:bg-[#da3633] dark:hover:text-white border border-[#d0d7de] dark:border-[#30363d] shadow-2xs',
        outline:
          'bg-[#f6f8fa] hover:bg-[#eaeef2] text-[#1f2328] dark:bg-[#21262d] dark:hover:bg-[#30363d] dark:text-[#c9d1d9] border border-[#d0d7de] dark:border-[#30363d] shadow-2xs',
        secondary:
          'bg-[#eaeef2] hover:bg-[#d8dee4] text-[#1f2328] dark:bg-[#30363d] dark:hover:bg-[#3c444d] dark:text-[#e6edf3] border border-[#d0d7de] dark:border-[#30363d]',
        ghost:
          'text-[#1f2328] dark:text-[#e6edf3] hover:bg-[#f6f8fa] dark:hover:bg-[#21262d]',
        link: 'text-[#0969da] dark:text-[#58a6ff] hover:underline underline-offset-4',
      },
      size: {
        default: 'h-8 px-3 py-1.5',
        sm: 'h-7 rounded px-2.5 text-[11px]',
        lg: 'h-9 rounded-md px-4 text-sm',
        icon: 'h-8 w-8',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'default',
    },
  }
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, ...props }, ref) => {
    return (
      <button
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        {...props}
      />
    );
  }
);
Button.displayName = 'Button';

export { Button, buttonVariants };
