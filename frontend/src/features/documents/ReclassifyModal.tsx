import React, { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../../api/client';
import { DocumentView, SecurityLevelName } from '../../api/types';
import { Dialog, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '../../components/ui/dialog';
import { Button } from '../../components/ui/button';
import { ProblemAlert } from '../../components/common/ProblemAlert';
import { ShieldCheck, AlertTriangle } from 'lucide-react';

interface ReclassifyModalProps {
  document: DocumentView | null;
  onClose: () => void;
}

export const ReclassifyModal: React.FC<ReclassifyModalProps> = ({
  document,
  onClose,
}) => {
  const queryClient = useQueryClient();

  const [targetLevel, setTargetLevel] = useState<SecurityLevelName>(
    document?.security_level_name || 'internal'
  );
  const [docTypeName, setDocTypeName] = useState(document?.doc_type_name || '');
  const [reason, setReason] = useState('');
  const [error, setError] = useState<any>(null);

  React.useEffect(() => {
    if (document) {
      setTargetLevel(document.security_level_name || 'internal');
      setDocTypeName(document.doc_type_name || '');
      setReason('');
      setError(null);
    }
  }, [document]);

  const reclassifyMutation = useMutation({
    mutationFn: async () => {
      if (!document) return;
      return api.post(`/v1/documents/${document.id}/reclassify`, {
        security_level_name: targetLevel,
        doc_type_name: docTypeName || undefined,
        reason: reason || 'Human operator reclassification',
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

  const currentLevelName = document?.security_level_name
    ? document.security_level_name.toLowerCase()
    : 'internal';
  const isLowering =
    ['restricted', 'confidential'].includes(currentLevelName) &&
    ['public', 'internal'].includes(targetLevel.toLowerCase());

  return (
    <Dialog open={!!document} onOpenChange={(open) => !open && onClose()}>
      <DialogHeader>
        <DialogTitle className="flex items-center gap-2">
          <ShieldCheck className="w-4 h-4 text-[#0969da] dark:text-[#2f81f7]" />
          Reclassify Document
        </DialogTitle>
        <DialogDescription>
          Apply a human classification override for: <strong className="text-[#1f2328] dark:text-[#e6edf3]">{document?.title}</strong>
        </DialogDescription>
      </DialogHeader>

      <form onSubmit={handleSubmit} className="p-4 sm:p-5 space-y-4 text-xs">
        <ProblemAlert error={error} />

        {isLowering && (
          <div className="p-2.5 bg-[#fff8c5] dark:bg-[#9e6a03]/30 border border-[#d4a72c]/40 text-[#9a6700] dark:text-[#f2cc60] rounded-md flex items-start gap-2">
            <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
            <p className="text-[11px] leading-relaxed">
              <strong>Security Warning (Invariant #8):</strong> Lowering a security level triggers a mandatory audit write and is validated by the database `check_monotonic` trigger.
            </p>
          </div>
        )}

        <div>
          <label className="block font-semibold text-[#1f2328] dark:text-[#e6edf3] mb-1">
            New Security Level
          </label>
          <select
            value={targetLevel}
            onChange={(e) => setTargetLevel(e.target.value as SecurityLevelName)}
            className="w-full h-8 rounded-md border border-[#d0d7de] dark:border-[#30363d] bg-white dark:bg-[#0d1117] text-[#1f2328] dark:text-[#e6edf3] px-2.5 text-xs focus:outline-none focus:ring-2 focus:ring-[#0969da]"
          >
            <option value="public">Public (Rank 1)</option>
            <option value="internal">Internal (Rank 2)</option>
            <option value="confidential">Confidential (Rank 3)</option>
            <option value="restricted">Restricted (Rank 4)</option>
          </select>
        </div>

        <div>
          <label className="block font-semibold text-[#1f2328] dark:text-[#e6edf3] mb-1">
            New Document Type
          </label>
          <input
            type="text"
            value={docTypeName}
            onChange={(e) => setDocTypeName(e.target.value)}
            placeholder="e.g. Contract › Vendor MSA"
            className="w-full h-8 rounded-md border border-[#d0d7de] dark:border-[#30363d] bg-white dark:bg-[#0d1117] text-[#1f2328] dark:text-[#e6edf3] px-2.5 text-xs focus:outline-none focus:ring-2 focus:ring-[#0969da]"
          />
        </div>

        <div>
          <label className="block font-semibold text-[#1f2328] dark:text-[#e6edf3] mb-1">
            Justification / Reason (Audited)
          </label>
          <textarea
            rows={2}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Provide legal or operational justification for this change..."
            required
            className="w-full rounded-md border border-[#d0d7de] dark:border-[#30363d] bg-white dark:bg-[#0d1117] text-[#1f2328] dark:text-[#e6edf3] p-2 text-xs focus:outline-none focus:ring-2 focus:ring-[#0969da]"
          />
        </div>

        <DialogFooter className="p-0 border-0 pt-2">
          <Button type="button" variant="outline" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button
            type="submit"
            size="sm"
            variant="default"
            disabled={reclassifyMutation.isPending}
          >
            {reclassifyMutation.isPending ? 'Saving...' : 'Apply Reclassification'}
          </Button>
        </DialogFooter>
      </form>
    </Dialog>
  );
};
