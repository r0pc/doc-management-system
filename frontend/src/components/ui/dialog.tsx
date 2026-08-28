import * as React from 'react';
import { X } from 'lucide-react';
import { cn } from '../../lib/utils';
import { trapFocus } from '../../lib/focus-trap';

interface DialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  children: React.ReactNode;
}

export function Dialog({ open, onOpenChange, children }: DialogProps) {
  const closeButtonRef = React.useRef<HTMLButtonElement>(null);
  const panelRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    if (!open) return;

    const activeElement = document.activeElement as HTMLElement | null;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onOpenChange(false);
    };

    document.addEventListener('keydown', handleKeyDown);
    document.body.style.overflow = 'hidden';

    // Move focus into the dialog synchronously. The old 50ms setTimeout left
    // focus on the trigger behind the overlay for three frames, and fired even
    // if the dialog had already closed.
    closeButtonRef.current?.focus();

    const releaseFocus = panelRef.current ? trapFocus(panelRef.current) : () => {};

    return () => {
      releaseFocus();
      document.removeEventListener('keydown', handleKeyDown);
      document.body.style.overflow = '';
      activeElement?.focus();
    };
  }, [open, onOpenChange]);

  if (!open) return null;

  return (
    <div 
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-[rgba(1,4,9,0.75)] backdrop-blur-2xs animate-in fade-in duration-100"
      role="dialog"
      aria-modal="true"
      aria-labelledby="dialog-title"
    >
      <div
        className="fixed inset-0"
        onClick={() => onOpenChange(false)}
        aria-hidden="true"
      />
      <div
        ref={panelRef}
        className="relative z-50 w-full max-w-lg rounded-md bg-white dark:bg-[#161b22] text-[#1f2328] dark:text-[#e6edf3] shadow-2xl border border-[#d0d7de] dark:border-[#30363d] overflow-hidden animate-in zoom-in-95 duration-100"
      >
        <button
          ref={closeButtonRef}
          type="button"
          aria-label="Close dialog"
          onClick={() => onOpenChange(false)}
          className="absolute right-3.5 top-3.5 rounded-sm p-1 text-[#656d76] dark:text-[#848d97] hover:text-[#1f2328] dark:hover:text-[#e6edf3] hover:bg-[#eaeef2] dark:hover:bg-[#30363d] transition-colors"
        >
          <X className="h-4 w-4" aria-hidden="true" />
          <span className="sr-only">Close</span>
        </button>
        {children}
      </div>
    </div>
  );
}

export function DialogHeader({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        'flex flex-col space-y-1 p-4 sm:p-5 border-b border-[#d0d7de] dark:border-[#30363d] bg-[#f6f8fa] dark:bg-[#161b22]',
        className
      )}
      {...props}
    />
  );
}

export function DialogTitle({
  className,
  ...props
}: React.HTMLAttributes<HTMLHeadingElement>) {
  return (
    <h2
      id={props.id || "dialog-title"}
      className={cn(
        'text-sm font-semibold leading-none tracking-tight text-[#1f2328] dark:text-[#e6edf3]',
        className
      )}
      {...props}
    />
  );
}

export function DialogDescription({
  className,
  ...props
}: React.HTMLAttributes<HTMLParagraphElement>) {
  return (
    <p
      className={cn('text-xs text-[#656d76] dark:text-[#848d97] mt-1', className)}
      {...props}
    />
  );
}

export function DialogFooter({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        'flex flex-col-reverse sm:flex-row sm:justify-end sm:space-x-2 p-4 sm:p-5 border-t border-[#d0d7de] dark:border-[#30363d] bg-[#f6f8fa] dark:bg-[#161b22]',
        className
      )}
      {...props}
    />
  );
}
