import React, { useState, useEffect, useMemo, useRef } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../../api/client';
import { DocumentListItem, BulkRenameRequest, BulkRenameResponse } from '../../api/types';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import { ProblemAlert } from '../../components/common/ProblemAlert';
import { trapFocus } from '../../lib/focus-trap';
import { X, ArrowRight, FileEdit, Check, RefreshCw } from 'lucide-react';

interface BulkRenameModalProps {
  isOpen: boolean;
  documents: DocumentListItem[];
  onClose: () => void;
  onSuccess: () => void;
}

export const BulkRenameModal: React.FC<BulkRenameModalProps> = ({
  isOpen,
  documents,
  onClose,
  onSuccess,
}) => {
  const queryClient = useQueryClient();
  const [prefix, setPrefix] = useState('');
  const [suffix, setSuffix] = useState('');
  const [findText, setFindText] = useState('');
  const [replaceText, setReplaceText] = useState('');
  const [caseSensitive, setCaseSensitive] = useState(false);
  const [preserveExtension, setPreserveExtension] = useState(true);
  const [customOverrides, setCustomOverrides] = useState<Record<string, string>>({});
  const [error, setError] = useState<unknown>(null);
  const modalRef = useRef<HTMLDivElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!isOpen) return;

    const activeElement = document.activeElement as HTMLElement | null;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };

    document.addEventListener('keydown', handleKeyDown);
    document.body.style.overflow = 'hidden';
    closeButtonRef.current?.focus();
    const releaseFocus = modalRef.current ? trapFocus(modalRef.current) : () => {};

    return () => {
      releaseFocus();
      document.removeEventListener('keydown', handleKeyDown);
      document.body.style.overflow = '';
      activeElement?.focus();
    };
  }, [isOpen, onClose]);

  // Reset state on open
  useEffect(() => {
    if (isOpen) {
      setPrefix('');
      setSuffix('');
      setFindText('');
      setReplaceText('');
      setCustomOverrides({});
      setError(null);
    }
  }, [isOpen]);

  const previewItems = useMemo(() => {
    return documents.map((doc) => {
      if (customOverrides[doc.id] !== undefined) {
        return {
          document: doc,
          newFilename: customOverrides[doc.id],
          isModified: customOverrides[doc.id] !== doc.filename,
        };
      }

      let baseName = doc.filename;
      let ext = '';

      if (preserveExtension && doc.filename.includes('.')) {
        const lastDot = doc.filename.lastIndexOf('.');
        baseName = doc.filename.substring(0, lastDot);
        ext = doc.filename.substring(lastDot);
      }

      let transformed = baseName;
      if (findText) {
        if (caseSensitive) {
          transformed = transformed.split(findText).join(replaceText);
        } else {
          const regex = new RegExp(findText.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi');
          transformed = transformed.replace(regex, replaceText);
        }
      }

      const newFilename = `${prefix}${transformed}${suffix}${ext}`.trim();
      return {
        document: doc,
        newFilename: newFilename || doc.filename,
        isModified: (newFilename || doc.filename) !== doc.filename,
      };
    });
  }, [documents, prefix, suffix, findText, replaceText, caseSensitive, preserveExtension, customOverrides]);

  const modifiedCount = previewItems.filter((i) => i.isModified).length;

  const bulkRenameMutation = useMutation({
    mutationFn: async (payload: BulkRenameRequest) => {
      return api.post<BulkRenameResponse>('/v1/documents/bulk-rename', payload);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents'] });
      onSuccess();
      onClose();
    },
    onError: (err) => {
      setError(err);
    },
  });

  const handleApply = (e: React.FormEvent) => {
    e.preventDefault();
    const itemsToSubmit = previewItems
      .filter((i) => i.isModified && i.newFilename.trim().length > 0)
      .map((i) => ({
        document_id: i.document.id,
        new_filename: i.newFilename.trim(),
      }));

    if (itemsToSubmit.length === 0) {
      onClose();
      return;
    }

    bulkRenameMutation.mutate({ items: itemsToSubmit });
  };

  const handleCustomOverride = (docId: string, value: string) => {
    setCustomOverrides((prev) => ({
      ...prev,
      [docId]: value,
    }));
  };

  const handleResetOverrides = () => {
    setCustomOverrides({});
  };

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 overflow-y-auto bg-[rgba(1,4,9,0.75)] backdrop-blur-2xs flex items-center justify-center p-4 animate-in fade-in duration-100"
      role="dialog"
      aria-modal="true"
      aria-labelledby="bulk-rename-title"
    >
      <div className="fixed inset-0" onClick={onClose} aria-hidden="true" />
      <div
        ref={modalRef}
        className="relative bg-white dark:bg-[#161b22] border border-[#d0d7de] dark:border-[#30363d] rounded-lg shadow-2xl w-full max-w-3xl max-h-[90vh] flex flex-col z-10 transition-colors"
      >
        {/* Header */}
        <div className="p-4 sm:p-5 border-b border-[#d0d7de] dark:border-[#30363d] flex items-center justify-between bg-[#f6f8fa] dark:bg-[#161b22] rounded-t-lg">
          <div className="flex items-center gap-2">
            <FileEdit className="w-4 h-4 text-[#0969da] dark:text-[#2f81f7]" />
            <h3 id="bulk-rename-title" className="font-semibold text-sm text-[#1f2328] dark:text-[#e6edf3]">
              Bulk Rename Documents ({documents.length} selected)
            </h3>
          </div>
          <button
            ref={closeButtonRef}
            type="button"
            onClick={onClose}
            aria-label="Close bulk rename modal"
            className="p-1 rounded-sm text-[#656d76] dark:text-[#848d97] hover:text-[#1f2328] dark:hover:text-[#e6edf3] hover:bg-[#eaeef2] dark:hover:bg-[#30363d] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0969da]"
          >
            <X className="w-4 h-4" aria-hidden="true" />
            <span className="sr-only">Close</span>
          </button>
        </div>

        {/* Content */}
        <form onSubmit={handleApply} className="flex-1 flex flex-col overflow-hidden">
          <div className="p-5 space-y-4 overflow-y-auto">
            <ProblemAlert error={error} />

            {/* Transformation Controls */}
            <div className="p-4 rounded-lg bg-[#f6f8fa] dark:bg-[#0d1117] border border-[#d0d7de] dark:border-[#30363d] space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-[#1f2328] dark:text-[#e6edf3] mb-1">
                    Add Prefix
                  </label>
                  <Input
                    type="text"
                    placeholder="e.g. [PROCESSED] _"
                    value={prefix}
                    onChange={(e) => setPrefix(e.target.value)}
                    className="h-8 text-xs bg-white dark:bg-[#161b22]"
                    aria-label="Add prefix to filenames"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-[#1f2328] dark:text-[#e6edf3] mb-1">
                    Add Suffix
                  </label>
                  <Input
                    type="text"
                    placeholder="e.g. _v2"
                    value={suffix}
                    onChange={(e) => setSuffix(e.target.value)}
                    className="h-8 text-xs bg-white dark:bg-[#161b22]"
                    aria-label="Add suffix to filenames"
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-[#1f2328] dark:text-[#e6edf3] mb-1">
                    Find Text
                  </label>
                  <Input
                    type="text"
                    placeholder="e.g. draft"
                    value={findText}
                    onChange={(e) => setFindText(e.target.value)}
                    className="h-8 text-xs bg-white dark:bg-[#161b22]"
                    aria-label="Find text in filenames"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-[#1f2328] dark:text-[#e6edf3] mb-1">
                    Replace With
                  </label>
                  <Input
                    type="text"
                    placeholder="e.g. final"
                    value={replaceText}
                    onChange={(e) => setReplaceText(e.target.value)}
                    className="h-8 text-xs bg-white dark:bg-[#161b22]"
                    aria-label="Replace text in filenames"
                  />
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-4 pt-1 text-xs text-[#656d76] dark:text-[#848d97]">
                <label className="flex items-center gap-1.5 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={preserveExtension}
                    onChange={(e) => setPreserveExtension(e.target.checked)}
                    className="rounded border-[#d0d7de] dark:border-[#30363d] text-[#0969da] focus:ring-[#0969da]"
                  />
                  <span>Preserve file extensions</span>
                </label>
                <label className="flex items-center gap-1.5 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={caseSensitive}
                    onChange={(e) => setCaseSensitive(e.target.checked)}
                    className="rounded border-[#d0d7de] dark:border-[#30363d] text-[#0969da] focus:ring-[#0969da]"
                  />
                  <span>Case sensitive search</span>
                </label>
                {Object.keys(customOverrides).length > 0 && (
                  <button
                    type="button"
                    onClick={handleResetOverrides}
                    className="flex items-center gap-1 text-[#0969da] dark:text-[#2f81f7] hover:underline ml-auto"
                  >
                    <RefreshCw className="w-3 h-3" />
                    Reset manual overrides
                  </button>
                )}
              </div>
            </div>

            {/* Live Preview List */}
            <div className="space-y-2">
              <div className="flex items-center justify-between text-xs font-semibold text-[#1f2328] dark:text-[#e6edf3]">
                <span>Transformation Preview</span>
                <span className="text-[11px] font-normal text-[#656d76] dark:text-[#848d97]">
                  {modifiedCount} of {documents.length} filename(s) will change
                </span>
              </div>

              <div className="border border-[#d0d7de] dark:border-[#30363d] rounded-md overflow-hidden max-h-60 overflow-y-auto">
                <table className="w-full text-left text-xs border-collapse">
                  <thead className="bg-[#f6f8fa] dark:bg-[#161b22] border-b border-[#d0d7de] dark:border-[#30363d] sticky top-0">
                    <tr>
                      <th className="p-2.5 font-semibold text-[#656d76] dark:text-[#848d97] w-1/2">
                        Original Filename
                      </th>
                      <th className="p-2.5 font-semibold text-[#656d76] dark:text-[#848d97] w-1/2">
                        New Filename (Editable)
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#d0d7de] dark:divide-[#30363d] bg-white dark:bg-[#0d1117]">
                    {previewItems.map(({ document: doc, newFilename, isModified }) => (
                      <tr
                        key={doc.id}
                        className={isModified ? 'bg-blue-50/30 dark:bg-blue-950/10' : ''}
                      >
                        <td className="p-2.5 text-[#656d76] dark:text-[#848d97] font-mono text-[11px] truncate max-w-xs" title={doc.filename}>
                          {doc.filename}
                        </td>
                        <td className="p-2">
                          <div className="flex items-center gap-1.5">
                            <ArrowRight className="w-3 h-3 text-[#656d76] dark:text-[#848d97] shrink-0" />
                            <Input
                              type="text"
                              value={newFilename}
                              onChange={(e) => handleCustomOverride(doc.id, e.target.value)}
                              className={`h-7 text-xs font-mono px-2 py-0 ${
                                isModified
                                  ? 'border-blue-400 dark:border-blue-600 bg-blue-50/20 dark:bg-blue-950/20 text-[#0969da] dark:text-[#2f81f7] font-semibold'
                                  : 'text-[#1f2328] dark:text-[#e6edf3]'
                              }`}
                              aria-label={`New filename for ${doc.filename}`}
                            />
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          {/* Footer */}
          <div className="p-4 sm:p-5 border-t border-[#d0d7de] dark:border-[#30363d] bg-[#f6f8fa] dark:bg-[#161b22] flex items-center justify-between rounded-b-lg">
            <span className="text-xs text-[#656d76] dark:text-[#848d97]">
              {modifiedCount === 0
                ? 'No changes applied yet'
                : `Ready to rename ${modifiedCount} document(s)`}
            </span>
            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={onClose}
                disabled={bulkRenameMutation.isPending}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                variant="default"
                size="sm"
                disabled={bulkRenameMutation.isPending || modifiedCount === 0}
              >
                <Check className="w-3.5 h-3.5 mr-1" />
                {bulkRenameMutation.isPending
                  ? 'Renaming...'
                  : `Apply Rename (${modifiedCount})`}
              </Button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
};
