import React, { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../../api/client';
import { DocumentListItem, SecurityLevelName } from '../../api/types';
import { Dialog, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '../../components/ui/dialog';
import { Button } from '../../components/ui/button';
import { ProblemAlert } from '../../components/common/ProblemAlert';
import {
  isLoweringLevel,
  justificationIsSufficient,
  MIN_JUSTIFICATION_LENGTH,
} from '../../security/levels';
import { ShieldCheck, AlertTriangle } from 'lucide-react';

interface ReclassifyModalProps {
  document: DocumentListItem | null;
  onClose: () => void;
}

export const ReclassifyModal: React.FC<ReclassifyModalProps> = ({
  document,
  onClose,
}) => {
  const queryClient = useQueryClient();

  const [targetLevel, setTargetLevel] = useState<SecurityLevelName>(
    (document?.level as SecurityLevelName) || 'Internal'
  );
  // Backend expects doc_type_id, we'll just mock null for now since we don't have a picker
  const [docTypeId, setDocTypeId] = useState<string | null>(null);
  const [justification, setJustification] = useState('');
  const [error, setError] = useState<unknown>(null);

  React.useEffect(() => {
    if (document) {
      setTargetLevel((document.level as SecurityLevelName) || 'Internal');
      setDocTypeId(null); // Reset
      setJustification('');
      setError(null);
    }
  }, [document]);

  const isLowering = isLoweringLevel(document?.level, targetLevel);
  const justificationOk = !isLowering || justificationIsSufficient(justification);

  const reclassifyMutation = useMutation({
    mutationFn: async () => {
      if (!document) throw new Error('No document selected.');
      // Guard the request itself, not just the button: a disabled submit is a
      // hint, and this mutation is reachable from anywhere the modal is.
      if (!justificationOk) {
        throw new Error(
          `Lowering a security level requires a justification of at least ${MIN_JUSTIFICATION_LENGTH} characters.`
        );
      }
      return api.post(`/v1/documents/${document.id}/classification`, {
        level_name: targetLevel.toLowerCase(), // backend LevelName enum is lowercase
        doc_type_id: docTypeId,
        ...(isLowering ? { justification: justification.trim() } : {}),
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

  return (
    <Dialog open={!!document} onOpenChange={(open) => !open && onClose()}>
      <DialogHeader>
        <DialogTitle className="flex items-center gap-2">
          <ShieldCheck className="w-4 h-4 text-[#0969da] dark:text-[#2f81f7]" />
          Reclassify Document
        </DialogTitle>
        <DialogDescription>
          Apply a human classification override for: <strong className="text-[#1f2328] dark:text-[#e6edf3]">{document?.filename}</strong>
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
              <strong>Security Warning (Invariant #8):</strong> Lowering a security level is a
              decision only a human may make. It triggers a mandatory audit write and is validated
              by the database `check_monotonic` trigger.
            </p>
          </div>
        )}

        <div>
          <label
            htmlFor="reclassify-level"
            className="block font-semibold text-[#1f2328] dark:text-[#e6edf3] mb-1"
          >
            New Security Level
          </label>
          <select
            id="reclassify-level"
            value={targetLevel}
            onChange={(e) => setTargetLevel(e.target.value as SecurityLevelName)}
            className="w-full h-8 rounded-md border border-[#d0d7de] dark:border-[#30363d] bg-white dark:bg-[#0d1117] text-[#1f2328] dark:text-[#e6edf3] px-2.5 text-xs focus:outline-none focus:ring-2 focus:ring-[#0969da]"
          >
            <option value="Public">Public (Rank 1)</option>
            <option value="Internal">Internal (Rank 2)</option>
            <option value="Confidential">Confidential (Rank 3)</option>
            <option value="Restricted">Restricted (Rank 4)</option>
          </select>
        </div>

        {isLowering && (
          <div>
            <label
              htmlFor="reclassify-justification"
              className="block font-semibold text-[#1f2328] dark:text-[#e6edf3] mb-1"
            >
              Justification for lowering the level{' '}
              <span className="text-[#cf222e] dark:text-[#f85149]">(required)</span>
            </label>
            <textarea
              id="reclassify-justification"
              value={justification}
              onChange={(e) => setJustification(e.target.value)}
              rows={3}
              required
              aria-describedby="reclassify-justification-hint"
              aria-invalid={!justificationOk}
              placeholder="Why is this document safe at the lower level? Reference the review or approval."
              className="w-full rounded-md border border-[#d0d7de] dark:border-[#30363d] bg-white dark:bg-[#0d1117] text-[#1f2328] dark:text-[#e6edf3] px-2.5 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-[#0969da]"
            />
            <p
              id="reclassify-justification-hint"
              className="text-[11px] text-[#656d76] dark:text-[#848d97] mt-1"
            >
              At least {MIN_JUSTIFICATION_LENGTH} characters. A downgrade is the one classification
              write no automated layer may perform.
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
            disabled={reclassifyMutation.isPending || !justificationOk}
          >
            {reclassifyMutation.isPending ? 'Saving...' : 'Apply Reclassification'}
          </Button>
        </DialogFooter>
      </form>
    </Dialog>
  );
};
