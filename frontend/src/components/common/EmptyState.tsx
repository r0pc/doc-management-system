import React from 'react';
import { FolderOpen } from 'lucide-react';
import { Button } from '../ui/button';

interface EmptyStateProps {
  icon?: React.ReactNode;
  title: string;
  description: string;
  actionLabel?: string;
  onAction?: () => void;
}

export function EmptyState({
  icon = <FolderOpen className="w-8 h-8 text-[#656d76] dark:text-[#848d97]" />,
  title,
  description,
  actionLabel,
  onAction,
}: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center p-10 text-center bg-white dark:bg-[#161b22] rounded-md border border-dashed border-[#d0d7de] dark:border-[#30363d] transition-colors">
      <div className="p-2.5 bg-[#f6f8fa] dark:bg-[#21262d] rounded-full mb-3 text-[#656d76] dark:text-[#848d97] border border-[#d0d7de] dark:border-[#30363d]">
        {icon}
      </div>
      <h3 className="text-sm font-semibold text-[#1f2328] dark:text-[#e6edf3] mb-1">{title}</h3>
      <p className="text-xs text-[#656d76] dark:text-[#848d97] max-w-sm mb-4 leading-relaxed">{description}</p>
      {actionLabel && onAction && (
        <Button onClick={onAction} size="sm" variant="default">
          {actionLabel}
        </Button>
      )}
    </div>
  );
}
