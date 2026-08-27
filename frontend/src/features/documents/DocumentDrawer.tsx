import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import { DocumentView, FindingOut, JobOut } from '../../api/types';
import { LevelBadge } from '../../components/common/LevelBadge';
import { Button } from '../../components/ui/button';
import { Dialog, DialogHeader, DialogTitle, DialogDescription } from '../../components/ui/dialog';
import { LoadingSkeleton } from '../../components/common/LoadingSkeleton';
import { ProblemAlert } from '../../components/common/ProblemAlert';
import { Can } from '../../security/Can';
import { Action } from '../../security/permissions';
import { formatBytes } from '../../lib/utils';
import {
  Download,
  Shield,
  Clock,
  CheckCircle2,
  XCircle,
  FileText,
  RotateCcw,
} from 'lucide-react';

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
  const [downloading, setDownloading] = React.useState(false);
  const [downloadError, setDownloadError] = React.useState<any>(null);

  const {
    data: document,
    isLoading: docLoading,
    error: docError,
  } = useQuery({
    queryKey: ['document', documentId],
    queryFn: () => api.get<DocumentView>(`/v1/documents/${documentId}`),
    enabled: !!documentId,
  });

  const { data: findings, isLoading: findingsLoading } = useQuery({
    queryKey: ['findings', documentId],
    queryFn: () => api.get<FindingOut[]>(`/v1/documents/${documentId}/findings`),
    enabled: !!documentId,
  });

  const { data: jobs, isLoading: jobsLoading } = useQuery({
    queryKey: ['jobs', documentId],
    queryFn: () => api.get<JobOut[]>(`/v1/documents/${documentId}/jobs`),
    enabled: !!documentId,
  });

  const handleDownload = async () => {
    if (!documentId) return;
    try {
      setDownloading(true);
      setDownloadError(null);
      const { blob, filename } = await api.fetchDocumentContent(documentId);
      const url = window.URL.createObjectURL(blob);
      const a = window.document.createElement('a');
      a.href = url;
      a.download = filename;
      window.document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      window.document.body.removeChild(a);
    } catch (err) {
      setDownloadError(err);
    } finally {
      setDownloading(false);
    }
  };

  return (
    <Dialog open={!!documentId} onOpenChange={(open) => !open && onClose()}>
      <DialogHeader>
        <DialogTitle className="flex items-center gap-2">
          <FileText className="w-5 h-5 text-blue-600 shrink-0" />
          <span className="truncate">{document?.title || 'Document Details'}</span>
        </DialogTitle>
        <DialogDescription>
          ID: <code className="font-mono text-xs text-slate-600">{documentId}</code>
        </DialogDescription>
      </DialogHeader>

      <div className="space-y-6 max-h-[70vh] overflow-y-auto pr-1">
        <ProblemAlert error={docError || downloadError} />

        {docLoading ? (
          <LoadingSkeleton count={4} />
        ) : document ? (
          <div className="space-y-5 text-xs">
            {/* Security & Classification Summary */}
            <div className="p-4 rounded-xl bg-slate-50 border border-slate-200 grid grid-cols-2 gap-3">
              <div>
                <div className="text-slate-400 text-[11px] font-semibold uppercase">
                  Security Level
                </div>
                <div className="mt-1">
                  <LevelBadge
                    level={document.security_level_name}
                    rank={document.security_level_rank}
                  />
                </div>
              </div>
              <div>
                <div className="text-slate-400 text-[11px] font-semibold uppercase">
                  Document Type
                </div>
                <div className="mt-1 font-semibold text-slate-800">
                  {document.doc_type_name || 'Unclassified'}
                </div>
              </div>
              <div>
                <div className="text-slate-400 text-[11px] font-semibold uppercase">
                  Status
                </div>
                <div className="mt-1">
                  <span
                    className={`font-semibold capitalize ${
                      document.status === 'ready'
                        ? 'text-emerald-700'
                        : document.status === 'failed'
                        ? 'text-rose-700'
                        : 'text-amber-700'
                    }`}
                  >
                    {document.status}
                  </span>
                </div>
              </div>
              <div>
                <div className="text-slate-400 text-[11px] font-semibold uppercase">
                  Size & MIME
                </div>
                <div className="mt-1 font-mono text-slate-700">
                  {formatBytes(document.byte_size || 0)} · {document.mime_type || 'Unknown'}
                </div>
              </div>
            </div>

            {/* Actions Bar */}
            <div className="flex gap-2">
              <Can action={Action.DOWNLOAD} document={document}>
                <Button
                  size="sm"
                  onClick={handleDownload}
                  disabled={downloading}
                  className="flex-1"
                >
                  <Download className="w-4 h-4 mr-1.5" />
                  {downloading ? 'Downloading...' : 'Download Content'}
                </Button>
              </Can>

              <Can action={Action.RECLASSIFY} document={document}>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => onReclassify && onReclassify(document)}
                >
                  <RotateCcw className="w-4 h-4 mr-1.5 text-slate-500" />
                  Reclassify
                </Button>
              </Can>
            </div>

            {/* Sensitive Findings (Invariant #12: char offsets only) */}
            <div>
              <h4 className="font-bold text-slate-800 text-xs mb-2 flex items-center gap-1.5">
                <Shield className="w-4 h-4 text-amber-600" />
                Sensitive Findings (Char Offsets Only)
              </h4>
              {findingsLoading ? (
                <LoadingSkeleton count={2} />
              ) : findings && findings.length > 0 ? (
                <div className="divide-y divide-slate-100 border border-slate-200 rounded-lg overflow-hidden bg-white">
                  {findings.map((f) => (
                    <div key={f.id} className="p-2.5 flex items-center justify-between text-xs">
                      <div>
                        <span className="font-semibold text-slate-900 uppercase tracking-wider text-[11px]">
                          {f.entity_type}
                        </span>
                        <div className="text-[11px] text-slate-400 font-mono">
                          Page {f.page_no} · Offset [{f.char_start} : {f.char_end}]
                        </div>
                      </div>
                      <div className="text-right">
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-100 text-amber-800 font-mono font-semibold">
                          Score {f.score.toFixed(2)}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-slate-400 italic text-[11px]">
                  No PII entities detected in this document version.
                </p>
              )}
            </div>

            {/* Processing Jobs Timeline (Invariant #4) */}
            <div>
              <h4 className="font-bold text-slate-800 text-xs mb-2 flex items-center gap-1.5">
                <Clock className="w-4 h-4 text-blue-600" />
                Processing Jobs Journal
              </h4>
              {jobsLoading ? (
                <LoadingSkeleton count={3} />
              ) : jobs && jobs.length > 0 ? (
                <div className="space-y-1.5">
                  {jobs.map((j) => (
                    <div
                      key={j.id}
                      className="p-2 rounded border border-slate-100 bg-white flex items-center justify-between text-xs"
                    >
                      <div className="flex items-center gap-2">
                        {j.status === 'succeeded' && (
                          <CheckCircle2 className="w-4 h-4 text-emerald-600" />
                        )}
                        {j.status === 'failed' && (
                          <XCircle className="w-4 h-4 text-rose-600" />
                        )}
                        {j.status === 'running' && (
                          <Clock className="w-4 h-4 text-sky-600 animate-spin" />
                        )}
                        <span className="font-mono font-medium text-slate-700">
                          {j.stage}
                        </span>
                      </div>
                      <span
                        className={`text-[10px] font-semibold uppercase px-1.5 py-0.2 rounded ${
                          j.status === 'succeeded'
                            ? 'bg-emerald-50 text-emerald-700'
                            : j.status === 'failed'
                            ? 'bg-rose-50 text-rose-700'
                            : 'bg-sky-50 text-sky-700'
                        }`}
                      >
                        {j.status}
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-slate-400 italic text-[11px]">No job journal found.</p>
              )}
            </div>
          </div>
        ) : null}
      </div>
    </Dialog>
  );
};
