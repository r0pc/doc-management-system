import { cn } from '../../lib/utils';

export function LoadingSkeleton({
  className,
  count = 3,
}: {
  className?: string;
  count?: number;
}) {
  return (
    <div className="space-y-2.5 w-full animate-pulse">
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          className={cn('h-9 bg-[#eaeef2] dark:bg-[#21262d] rounded-md w-full', className)}
        />
      ))}
    </div>
  );
}

export function TableSkeleton({ rows = 5, cols = 5 }: { rows?: number; cols?: number }) {
  return (
    <div className="w-full space-y-2 p-3 bg-white dark:bg-[#161b22] rounded-md border border-[#d0d7de] dark:border-[#30363d] transition-colors">
      <div className="h-7 bg-[#eaeef2] dark:bg-[#21262d] rounded w-full mb-3 animate-pulse" />
      {Array.from({ length: rows }).map((_, r) => (
        <div key={r} className="flex gap-3 items-center animate-pulse">
          {Array.from({ length: cols }).map((_, c) => (
            <div
              key={c}
              className="h-6 bg-[#f6f8fa] dark:bg-[#21262d]/60 rounded flex-1"
              style={{ opacity: 1 - c * 0.1 }}
            />
          ))}
        </div>
      ))}
    </div>
  );
}
