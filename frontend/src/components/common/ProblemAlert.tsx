import { AlertTriangle } from 'lucide-react';
import { ApiError } from '../../api/client';

export function ProblemAlert({ error }: { error: any }) {
  if (!error) return null;

  const problem = error instanceof ApiError ? error.problem : null;
  const title = problem?.title || error.name || 'Error';
  const detail = problem?.detail || error.message || 'An unexpected error occurred.';
  const status = problem?.status || error.status;

  return (
    <div className="p-3.5 rounded-md bg-[#ffebe9] dark:bg-[#da3633]/20 border border-[#ff8182]/50 dark:border-[#f85149]/40 text-[#cf222e] dark:text-[#f85149] flex items-start gap-2.5 my-3 text-xs transition-colors">
      <AlertTriangle className="w-4 h-4 text-[#cf222e] dark:text-[#f85149] shrink-0 mt-0.5" />
      <div className="flex-1">
        <div className="font-semibold text-[#1f2328] dark:text-[#e6edf3] flex items-center gap-2">
          <span>{title}</span>
          {status && (
            <span className="text-[10px] px-1.5 py-0.2 rounded bg-[#ff8182]/20 dark:bg-[#da3633]/40 font-mono text-[#cf222e] dark:text-[#f85149]">
              HTTP {status}
            </span>
          )}
        </div>
        <p className="mt-0.5 text-[#1f2328]/90 dark:text-[#e6edf3]/90 text-[11px] leading-relaxed font-sans">{detail}</p>
      </div>
    </div>
  );
}
