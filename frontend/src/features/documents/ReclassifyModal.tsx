import React, { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../../api/client';
import { DocumentView, SecurityLevelName } from '../../api/types';
import { Dialog, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '../../components/ui/dialog';
import { Button } from '../../components/ui/button';
import { ProblemAlert } from '../../components/common/ProblemAlert';
import { Shield, AlertTriangle } from 'lucide-react';

interface ReclassifyModalProps {
  document: DocumentView | null;
  onClose: () => void;
}

export const ReclassifyModal: React.FC<ReclassifyModalProps> = ({
  document,
  onClose,
}) => {
  const queryClient = useQueryClient();

  const [level, setLevel] = useState<SecurityLevelName>(
    document?.security_level_name || 'internal'
  );
  const [docTypeName, setDocTypeName] = useState(document?.doc_type_name || '');
  const [reason, setReason] = useState('');
  const [error, setError] = useState<any>(null);

  React.useEffect(() => {
    if (document) {
      setLevel(document.security_level_name || 'internal');
      setDocTypeName(document.doc_type_name || '');
      setReason('');
      setError(null);
    }
  }, [document]);

  const reclassifyMutation = useMutation({
    mutationFn: async () => {
      if (!document) return;
      return api.post(`/v1/documents/${document.id}/classification`, {
        security_level_name: level,
        doc_type_name: docTypeName || undefined,
        reason: reason || 'Manual reclassification via web UI',
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents'] });
      queryClient.invalidateQueries({ queryKey: ['document', document?.id] });
      queryClient.invalidateQueries({ queryKey: ['audit'] });
      onClose();
    },
    onError: (err) => {
      setError(err);
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    reclassifyMutation.mutate();
  };

  const isLowering =
    document?.security_level_rank &&
    (level === 'public'
      ? 1
      : level === 'internal'
      ? 2
      : level === 'confidential'
      ? 3
      : 4) < document.security_level_rank;

  return (
    <Dialog open={!!document} onOpenChange={(open) => !open && onClose()}>
      <DialogHeader>
        <DialogTitle className="flex items-center gap-2">
          <Shield className="w-5 h-5 text-blue-600" />
          Reclassify Document
        </DialogTitle>
        <DialogDescription>
          Apply a human security level or document type override (Invariant #8 & #20).
        </DialogDescription>
      </DialogHeader>

      <form onSubmit={handleSubmit} className="space-y-4 text-xs">
        <ProblemAlert error={error} />

        {isLowering && (
          <div className="p-3 bg-amber-50 border border-amber-200 rounded-lg text-amber-900 flex items-start gap-2">
            <AlertTriangle className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
            <p className="text-[11px] leading-relaxed">
              <strong>Security Level Lowering:</strong> You are lowering the security rank. The database <code className="font-mono">check_monotonic</code> trigger allows this for human reviewers and records an immutable audit log entry.
            </p>
          </div>
        )}

        <div>
          <label className="block font-semibold text-slate-700 mb-1">
            New Security Level
          </label>
          <select
            value={level}
            onChange={(e) => setLevel(e.target.value as SecurityLevelName)}
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
            Document Type (Optional Override)
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
            Reason for Reclassification (Audited)
          </label>
          <textarea
            rows={2}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="State the justification for this classification write..."
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
            disabled={reclassifyMutation.isPending}
          >
            {reclassifyMutation.isPending ? 'Saving...' : 'Apply Classification'}
          </Button>
        </DialogFooter>
      </form>
    </Dialog>
  );
};
