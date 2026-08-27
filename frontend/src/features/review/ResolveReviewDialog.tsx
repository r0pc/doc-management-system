import React, { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../../api/client';
import { ReviewQueueItem, SecurityLevelName } from '../../api/types';
import { Dialog, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '../../components/ui/dialog';
import { Button } from '../../components/ui/button';
import { ProblemAlert } from '../../components/common/ProblemAlert';
import { CheckSquare } from 'lucide-react';

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
  const [error, setError] = useState<any>(null);

  React.useEffect(() => {
    if (item) {
      setSecurityLevel((item.level as SecurityLevelName) || 'Internal');
      setDocTypeId(null);
      setError(null);
    }
  }, [item]);

  const resolveMutation = useMutation({
    mutationFn: async () => {
      if (!item) return;
      const isAccept = item.level && securityLevel.toLowerCase() === item.level.toLowerCase();
      
      return api.post(`/v1/review/${item.review_id}/resolve`, {
        level_name: securityLevel.toLowerCase(),
        doc_type_id: docTypeId,
        decision: isAccept ? 'accept' : 'correct',
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

        <div>
          <label className="block font-semibold text-[#1f2328] dark:text-[#e6edf3] mb-1">
            Final Security Level (Human Decision)
          </label>
          <select
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

        <DialogFooter className="p-0 border-0 pt-2">
          <Button type="button" variant="outline" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button
            type="submit"
            size="sm"
            variant="default"
            disabled={resolveMutation.isPending}
          >
            {resolveMutation.isPending ? 'Resolving...' : 'Confirm Resolution'}
          </Button>
        </DialogFooter>
      </form>
    </Dialog>
  );
};
