import { AlertTriangle } from 'lucide-react';
import { ApiError } from '../../api/client';

export function ProblemAlert({ error }: { error: any }) {
  if (!error) return null;

  const problem = error instanceof ApiError ? error.problem : null;
  const title = problem?.title || error.name || 'Error';
  const detail = problem?.detail || error.message || 'An unexpected error occurred.';
  const status = problem?.status || error.status;

  return (
    <div className="p-4 rounded-lg bg-rose-50 border border-rose-200 text-rose-900 flex items-start gap-3 my-4">
      <AlertTriangle className="w-5 h-5 text-rose-600 shrink-0 mt-0.5" />
      <div className="text-sm">
        <div className="font-semibold text-rose-950 flex items-center gap-2">
          {title}
          {status && (
            <span className="text-xs px-1.5 py-0.5 rounded bg-rose-200/60 font-mono">
              {status}
            </span>
          )}
        </div>
        <p className="mt-1 text-rose-800 text-xs leading-relaxed">{detail}</p>
      </div>
    </div>
  );
}
