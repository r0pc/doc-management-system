import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import { DocumentView, JobOut, FindingOut } from '../../api/types';
import { LevelBadge } from '../../components/common/LevelBadge';
import { Button } from '../../components/ui/button';
import { LoadingSkeleton } from '../../components/common/LoadingSkeleton';
import { ProblemAlert } from '../../components/common/ProblemAlert';
import { formatBytes, formatDate } from '../../lib/utils';
import {
  X,
  Download,
  ShieldAlert,
  FileText,
  Clock,
  History,
  Sparkles,
} from 'lucide-react';
import { Can } from '../../security/Can';
import { Action } from '../../security/permissions';

interface DocumentDrawerProps {
  documentId: string | null;
  onClose: () => void;
  onReclassify?: (doc: DocumentView) => void;
}

export const DocumentDrawer: React.FC<DocumentDrawerProps> = ({
  documentId,
  onClose,
  onReclassify,
}) => {
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<any>(null);

  const { data: doc, isLoading, error } = useQuery({
    queryKey: ['document', documentId],
    queryFn: () => api.get<DocumentView>(`/v1/documents/${documentId}`),
    enabled: !!documentId,
  });

  const { data: jobs } = useQuery({
    queryKey: ['document', documentId, 'jobs'],
    queryFn: () => api.get<JobOut[]>(`/v1/documents/${documentId}/jobs`),
    enabled: !!documentId,
  });

  const { data: findings } = useQuery({
    queryKey: ['document', documentId, 'findings'],
    queryFn: () => api.get<FindingOut[]>(`/v1/documents/${documentId}/findings`),
    enabled: !!documentId,
  });

  const handleDownload = async () => {
    if (!doc) return;
    try {
      setDownloading(true);
      setDownloadError(null);

      const rank = doc.security_level_rank ?? 2;
      const levelName = doc.security_level_name ? doc.security_level_name.toLowerCase() : 'internal';
      const isHighClearance = rank >= 3 || ['confidential', 'restricted'].includes(levelName);

      if (isHighClearance) {
        // Streamed directly through API (Invariant #17)
        const { blob, filename } = await api.fetchDocumentContent(doc.id);
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename || doc.title || 'document';
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);
      } else {
        // Presigned redirect path
        const res = await fetch(`/v1/documents/${doc.id}/content`, {
          headers: {
            Authorization: `Bearer ${localStorage.getItem('dms_auth_token') || ''}`,
          },
          redirect: 'follow',
        });
        if (!res.ok) throw new Error(`Download failed: ${res.status}`);
        const blob = await res.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = doc.title || 'document';
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);
      }
    } catch (err: any) {
      setDownloadError(err);
    } finally {
      setDownloading(false);
    }
  };

  if (!documentId) return null;

  return (
    <div className="fixed inset-0 z-50 overflow-hidden bg-[rgba(1,4,9,0.75)] backdrop-blur-2xs animate-in fade-in duration-100">
      <div className="absolute inset-0" onClick={onClose} aria-hidden="true" />
      <div className="absolute inset-y-0 right-0 max-w-full flex pl-10">
        <div className="w-screen max-w-xl bg-white dark:bg-[#161b22] border-l border-[#d0d7de] dark:border-[#30363d] shadow-2xl flex flex-col transition-colors">
          {/* Header */}
          <div className="p-4 sm:p-5 border-b border-[#d0d7de] dark:border-[#30363d] flex items-center justify-between bg-[#f6f8fa] dark:bg-[#161b22]">
            <div className="flex items-center gap-2">
              <FileText className="w-4 h-4 text-[#656d76] dark:text-[#848d97]" />
              <h3 className="font-semibold text-sm text-[#1f2328] dark:text-[#e6edf3]">
                Document Inspector
              </h3>
            </div>
            <button
              onClick={onClose}
              className="p-1 rounded-sm text-[#656d76] dark:text-[#848d97] hover:text-[#1f2328] dark:hover:text-[#e6edf3] hover:bg-[#eaeef2] dark:hover:bg-[#30363d]"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* Body */}
          <div className="flex-1 overflow-y-auto p-5 space-y-6 text-xs text-[#1f2328] dark:text-[#e6edf3]">
            {isLoading ? (
              <LoadingSkeleton count={6} />
            ) : error ? (
              <ProblemAlert error={error} />
            ) : doc ? (
              <>
                <ProblemAlert error={downloadError} />

                {/* Primary Metadata Box */}
                <div className="space-y-3 pb-5 border-b border-[#d8dee4] dark:border-[#30363d]">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <h2 className="text-base font-bold text-[#1f2328] dark:text-[#e6edf3]">
                        {doc.title}
                      </h2>
                      <p className="text-[11px] font-mono text-[#656d76] dark:text-[#848d97] mt-0.5">
                        ID: {doc.id}
                      </p>
                    </div>
                    <LevelBadge
                      level={doc.security_level_name}
                      rank={doc.security_level_rank}
                    />
                  </div>

                  <div className="grid grid-cols-2 gap-2 text-xs p-3 bg-[#f6f8fa] dark:bg-[#21262d] rounded-md border border-[#d0d7de] dark:border-[#30363d]">
                    <div>
                      <span className="text-[#656d76] dark:text-[#848d97] block text-[11px]">Type:</span>
                      <span className="font-medium text-[#1f2328] dark:text-[#e6edf3]">
                        {doc.doc_type_name || 'Unclassified'}
                      </span>
                    </div>
                    <div>
                      <span className="text-[#656d76] dark:text-[#848d97] block text-[11px]">File Size:</span>
                      <span className="font-mono text-[#1f2328] dark:text-[#e6edf3]">
                        {formatBytes(doc.byte_size || 0)}
                      </span>
                    </div>
                    <div>
                      <span className="text-[#656d76] dark:text-[#848d97] block text-[11px]">MIME:</span>
                      <span className="font-mono text-[#1f2328] dark:text-[#e6edf3] text-[11px]">
                        {doc.mime_type || '—'}
                      </span>
                    </div>
                    <div>
                      <span className="text-[#656d76] dark:text-[#848d97] block text-[11px]">Department:</span>
                      <span className="font-mono text-[#1f2328] dark:text-[#e6edf3] text-[11px] truncate block">
                        {doc.department_id || '—'}
                      </span>
                    </div>
                  </div>
                </div>

                {/* Classification Actions */}
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <h4 className="font-semibold text-xs text-[#1f2328] dark:text-[#e6edf3] flex items-center gap-1.5">
                      <Sparkles className="w-3.5 h-3.5 text-[#0969da] dark:text-[#2f81f7]" />
                      Classification Actions
                    </h4>
                    {onReclassify && (
                      <Can action={Action.RECLASSIFY} document={doc}>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => onReclassify(doc)}
                          className="h-6 px-2 text-[11px]"
                        >
                          <History className="w-3 h-3 mr-1" /> Reclassify
                        </Button>
                      </Can>
                    )}
                  </div>
                </div>

                {/* Sensitive Findings Offsets (Invariant #12) */}
                <div className="space-y-2">
                  <h4 className="font-semibold text-xs text-[#1f2328] dark:text-[#e6edf3] flex items-center gap-1.5">
                    <ShieldAlert className="w-3.5 h-3.5 text-[#cf222e] dark:text-[#f85149]" />
                    Sensitive Findings (Offsets Only — Invariant #12)
                  </h4>
                  {findings && findings.length > 0 ? (
                    <div className="space-y-1.5">
                      {findings.map((f, i) => (
                        <div
                          key={i}
                          className="p-2 bg-white dark:bg-[#0d1117] rounded border border-[#d0d7de] dark:border-[#30363d] flex items-center justify-between text-xs"
                        >
                          <span className="font-semibold uppercase text-[10px] tracking-wider px-1.5 py-0.5 rounded bg-[#ffebe9] dark:bg-[#da3633]/25 text-[#cf222e] dark:text-[#f85149] border border-[#ff8182]/30">
                            {f.entity_type}
                          </span>
                          <span className="font-mono text-[#656d76] dark:text-[#848d97] text-[11px]">
                            Chars [{f.char_start}..{f.char_end}]
                          </span>
                          <span className="font-mono text-[11px] text-[#1f2328] dark:text-[#e6edf3]">
                            {(f.score * 100).toFixed(0)}% score
                          </span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-[#656d76] dark:text-[#848d97] text-xs italic">
                      No PII or sensitive patterns detected.
                    </p>
                  )}
                </div>

                {/* Processing Pipeline Timeline (Invariant #4) */}
                <div className="space-y-2">
                  <h4 className="font-semibold text-xs text-[#1f2328] dark:text-[#e6edf3] flex items-center gap-1.5">
                    <Clock className="w-3.5 h-3.5 text-[#0969da] dark:text-[#2f81f7]" />
                    Processing Pipeline Journal (Invariant #4)
                  </h4>
                  {jobs && jobs.length > 0 ? (
                    <div className="border border-[#d0d7de] dark:border-[#30363d] rounded-md divide-y divide-[#d8dee4] dark:divide-[#30363d] overflow-hidden">
                      {jobs.map((j, i) => (
                        <div
                          key={i}
                          className="p-2.5 bg-white dark:bg-[#0d1117] flex items-center justify-between text-xs"
                        >
                          <div className="flex items-center gap-2">
                            <span
                              className={`w-2 h-2 rounded-full ${
                                j.state === 'succeeded'
                                  ? 'bg-[#1a7f37] dark:bg-[#3fb950]'
                                  : j.state === 'failed'
                                  ? 'bg-[#cf222e] dark:bg-[#f85149]'
                                  : 'bg-[#9a6700] dark:bg-[#d29922]'
                              }`}
                            />
                            <span className="font-mono text-[#1f2328] dark:text-[#e6edf3]">
                              {j.stage}
                            </span>
                          </div>
                          <span className="text-[11px] text-[#656d76] dark:text-[#848d97]">
                            {j.finished_at ? formatDate(j.finished_at) : j.state}
                          </span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-[#656d76] dark:text-[#848d97] text-xs">
                      No pipeline stages recorded yet.
                    </p>
                  )}
                </div>
              </>
            ) : null}
          </div>

          {/* Footer Actions */}
          {doc && (
            <div className="p-4 border-t border-[#d0d7de] dark:border-[#30363d] bg-[#f6f8fa] dark:bg-[#161b22] flex items-center justify-between gap-3">
              <span className="text-[11px] text-[#656d76] dark:text-[#848d97]">
                Delivery: {(doc.security_level_rank ?? 2) >= 3 ? 'API Stream (Range)' : 'Presigned 303'}
              </span>
              <div className="flex items-center gap-2">
                <Can action={Action.DOWNLOAD} document={doc}>
                  <Button
                    size="sm"
                    variant="default"
                    onClick={handleDownload}
                    disabled={downloading}
                  >
                    <Download className="w-3.5 h-3.5 mr-1.5" />
                    {downloading ? 'Downloading...' : 'Download'}
                  </Button>
                </Can>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
