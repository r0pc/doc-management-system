import React, { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../../api/client';
import { ReviewQueueItem, SecurityLevelName } from '../../api/types';
import { Dialog, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '../../components/ui/dialog';
import { Button } from '../../components/ui/button';
import { ProblemAlert } from '../../components/common/ProblemAlert';
import {
  isLoweringLevel,
  justificationIsSufficient,
  MIN_JUSTIFICATION_LENGTH,
} from '../../security/levels';
import { CheckSquare, AlertTriangle } from 'lucide-react';

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
    (item?.level as SecurityLevelName) || 'Internal'
  );
  // Backend expects doc_type_id, mock null
  const [docTypeId, setDocTypeId] = useState<string | null>(null);
  const [justification, setJustification] = useState('');
  const [error, setError] = useState<unknown>(null);

  React.useEffect(() => {
    if (item) {
      setSecurityLevel((item.level as SecurityLevelName) || 'Internal');
      setDocTypeId(null);
      setJustification('');
      setError(null);
    }
  }, [item]);

  // Resolving a review is the other route by which a human lowers a label
  // (#8) — it needs the same gate the reclassify modal has, and previously had
  // none at all: the operator could downgrade Restricted to Public here with a
  // single click and no prompt.
  const isLowering = isLoweringLevel(item?.level, securityLevel);
  const justificationOk = !isLowering || justificationIsSufficient(justification);

  const resolveMutation = useMutation({
    mutationFn: async () => {
      if (!item) throw new Error('No review item selected.');
      if (!justificationOk) {
        throw new Error(
          `Lowering a security level requires a justification of at least ${MIN_JUSTIFICATION_LENGTH} characters.`
        );
      }
      const isAccept = !!item.level && securityLevel.toLowerCase() === item.level.toLowerCase();

      return api.post(`/v1/review/${item.review_id}/resolve`, {
        level_name: securityLevel.toLowerCase(),
        doc_type_id: docTypeId,
        decision: isAccept ? 'accept' : 'correct',
        // Not modelled by the API's ResolveReviewRequest yet, so it is dropped
        // server-side and NOT persisted. See ReclassifyModal for the same note:
        // this requirement lives in the UI only.
        ...(isLowering ? { justification: justification.trim() } : {}),
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
          <CheckSquare className="w-4 h-4 text-[#1a7f37] dark:text-[#3fb950]" />
          Resolve Review Item
        </DialogTitle>
        <DialogDescription>
          Confirm or override the classification for: <strong className="text-[#1f2328] dark:text-[#e6edf3]">{item?.filename}</strong>
        </DialogDescription>
      </DialogHeader>

      <form onSubmit={handleSubmit} className="p-4 sm:p-5 space-y-4 text-xs">
        <ProblemAlert error={error} />

        {isLowering && (
          <div
            role="alert"
            className="p-2.5 bg-[#fff8c5] dark:bg-[#9e6a03]/30 border border-[#d4a72c]/40 text-[#9a6700] dark:text-[#f2cc60] rounded-md flex items-start gap-2"
          >
            <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" aria-hidden="true" />
            <p className="text-[11px] leading-relaxed">
              <strong>Security Warning (Invariant #8):</strong> You are resolving this item BELOW
              the suggested level. Only a human may lower a label, and the write is audited.
            </p>
          </div>
        )}

        <div>
          <label
            htmlFor="resolve-level"
            className="block font-semibold text-[#1f2328] dark:text-[#e6edf3] mb-1"
          >
            Final Security Level (Human Decision)
          </label>
          <select
            id="resolve-level"
            value={securityLevel}
            onChange={(e) => setSecurityLevel(e.target.value as SecurityLevelName)}
            className="w-full h-8 rounded-md border border-[#d0d7de] dark:border-[#30363d] bg-white dark:bg-[#0d1117] text-[#1f2328] dark:text-[#e6edf3] px-2.5 text-xs focus:outline-none focus:ring-2 focus:ring-[#0969da]"
          >
            <option value="Public">Public (Rank 1)</option>
            <option value="Internal">Internal (Rank 2 - Default Floor)</option>
            <option value="Confidential">Confidential (Rank 3)</option>
            <option value="Restricted">Restricted (Rank 4)</option>
          </select>
        </div>

        {isLowering && (
          <div>
            <label
              htmlFor="resolve-justification"
              className="block font-semibold text-[#1f2328] dark:text-[#e6edf3] mb-1"
            >
              Justification for lowering the level{' '}
              <span className="text-[#cf222e] dark:text-[#f85149]">(required)</span>
            </label>
            <textarea
              id="resolve-justification"
              value={justification}
              onChange={(e) => setJustification(e.target.value)}
              rows={3}
              required
              aria-describedby="resolve-justification-hint"
              aria-invalid={!justificationOk}
              placeholder="Why is the suggested level too high for this document?"
              className="w-full rounded-md border border-[#d0d7de] dark:border-[#30363d] bg-white dark:bg-[#0d1117] text-[#1f2328] dark:text-[#e6edf3] px-2.5 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-[#0969da]"
            />
            <p
              id="resolve-justification-hint"
              className="text-[11px] text-[#656d76] dark:text-[#848d97] mt-1"
            >
              At least {MIN_JUSTIFICATION_LENGTH} characters.
            </p>
          </div>
        )}

        <DialogFooter className="p-0 border-0 pt-2">
          <Button type="button" variant="outline" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button
            type="submit"
            size="sm"
            variant="default"
            disabled={resolveMutation.isPending || !justificationOk}
          >
            {resolveMutation.isPending ? 'Resolving...' : 'Confirm Resolution'}
          </Button>
        </DialogFooter>
      </form>
    </Dialog>
  );
};
