import React, { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../../api/client';
import { ReviewQueueItem, SecurityLevelName } from '../../api/types';
import { Dialog, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '../../components/ui/dialog';
import { Button } from '../../components/ui/button';
import { ProblemAlert } from '../../components/common/ProblemAlert';
import { CheckSquare, AlertCircle } from 'lucide-react';

interface ResolveReviewDialogProps {
  item: ReviewQueueItem | null;
  onClose: () => void;
}

export const ResolveReviewDialog: React.FC<ResolveReviewDialogProps> = ({
  item,
  onClose,
}) => {
  const queryClient = useQueryClient();

  const [securityLevel, setSecurityLevel] = useState<SecurityLevelName>(
    item?.suggested_level_name || 'internal'
  );
  const [docTypeName, setDocTypeName] = useState(item?.suggested_doc_type_name || '');
  const [resolutionNotes, setResolutionNotes] = useState('');
  const [error, setError] = useState<any>(null);

  React.useEffect(() => {
    if (item) {
      setSecurityLevel(item.suggested_level_name || 'internal');
      setDocTypeName(item.suggested_doc_type_name || '');
      setResolutionNotes('');
      setError(null);
    }
  }, [item]);

  const resolveMutation = useMutation({
    mutationFn: async () => {
      if (!item) return;
      return api.post(`/v1/review/${item.id}/resolve`, {
        security_level_name: securityLevel,
        doc_type_name: docTypeName || undefined,
        resolution_notes: resolutionNotes || 'Resolved by human reviewer in UI',
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['review'] });
      queryClient.invalidateQueries({ queryKey: ['documents'] });
      queryClient.invalidateQueries({ queryKey: ['audit'] });
      onClose();
    },
    onError: (err) => {
      setError(err);
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    resolveMutation.mutate();
  };

  return (
    <Dialog open={!!item} onOpenChange={(open) => !open && onClose()}>
      <DialogHeader>
        <DialogTitle className="flex items-center gap-2">
          <CheckSquare className="w-5 h-5 text-emerald-600" />
          Resolve Review Item
        </DialogTitle>
        <DialogDescription>
          Confirm or override the suggested classification for: <strong className="text-slate-900">{item?.title}</strong>
        </DialogDescription>
      </DialogHeader>

      <form onSubmit={handleSubmit} className="space-y-4 text-xs">
        <ProblemAlert error={error} />

        <div className="p-3 bg-slate-50 border border-slate-200 rounded-lg space-y-1.5">
          <div className="text-[11px] font-semibold text-slate-500 uppercase">
            Cascade Trigger Reasons
          </div>
          <div className="space-y-1">
            {item?.reasons && item.reasons.length > 0 ? (
              item.reasons.map((r, i) => (
                <div key={i} className="flex items-start gap-1.5 text-slate-700 font-mono text-[11px]">
                  <AlertCircle className="w-3.5 h-3.5 text-amber-600 shrink-0 mt-0.5" />
                  <span>{r}</span>
                </div>
              ))
            ) : (
              <span className="text-slate-400">Standard review route.</span>
            )}
          </div>
        </div>

        <div>
          <label className="block font-semibold text-slate-700 mb-1">
            Final Security Level (Human Decision)
          </label>
          <select
            value={securityLevel}
            onChange={(e) => setSecurityLevel(e.target.value as SecurityLevelName)}
            className="w-full h-9 rounded-md border border-slate-300 bg-white px-3 text-xs focus:outline-none focus:ring-1 focus:ring-blue-600"
          >
            <option value="public">Public (Rank 1)</option>
            <option value="internal">Internal (Rank 2 - Default Floor)</option>
            <option value="confidential">Confidential (Rank 3)</option>
            <option value="restricted">Restricted (Rank 4)</option>
          </select>
        </div>

        <div>
          <label className="block font-semibold text-slate-700 mb-1">
            Final Document Type
          </label>
          <input
            type="text"
            value={docTypeName}
            onChange={(e) => setDocTypeName(e.target.value)}
            placeholder="e.g. Contract › Vendor MSA"
            className="w-full h-9 rounded-md border border-slate-300 bg-white px-3 text-xs focus:outline-none focus:ring-1 focus:ring-blue-600"
          />
        </div>

        <div>
          <label className="block font-semibold text-slate-700 mb-1">
            Resolution Notes (Audited)
          </label>
          <textarea
            rows={2}
            value={resolutionNotes}
            onChange={(e) => setResolutionNotes(e.target.value)}
            placeholder="Document rationale for this resolution..."
            required
            className="w-full rounded-md border border-slate-300 bg-white p-2 text-xs focus:outline-none focus:ring-1 focus:ring-blue-600"
          />
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button
            type="submit"
            size="sm"
            disabled={resolveMutation.isPending}
            className="bg-emerald-600 hover:bg-emerald-700 text-white"
          >
            {resolveMutation.isPending ? 'Resolving...' : 'Confirm Resolution'}
          </Button>
        </DialogFooter>
      </form>
    </Dialog>
  );
};
