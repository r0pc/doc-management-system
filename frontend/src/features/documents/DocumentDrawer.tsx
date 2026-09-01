import React, { useState, useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import { DocumentListItem, JobOut, FindingOut, DocumentPreviewOut } from '../../api/types';
import { LevelBadge } from '../../components/common/LevelBadge';
import { Button } from '../../components/ui/button';
import { LoadingSkeleton } from '../../components/common/LoadingSkeleton';
import { ProblemAlert } from '../../components/common/ProblemAlert';
import { formatDate } from '../../lib/utils';
import {
  X,
  Download,
  ExternalLink,
  ShieldAlert,
  ShieldCheck,
  FileText,
  Clock,
  History,
  Tag,
  Cpu,
  Eye,
} from 'lucide-react';
import { trapFocus } from '../../lib/focus-trap';
import { Can } from '../../security/Can';
import { Action } from '../../security/permissions';

/**
 * How a classification was reached, phrased so the number means what it says.
 *
 * Only the ML head produces a calibrated probability. A prototype match is a
 * cosine similarity, which invariant #11 forbids storing in `confidence` — so
 * that column is 0.0 for prototype hits, and rendering it as a percentage
 * would claim the classifier was 0% sure when it in fact matched above its
 * threshold. Prototype hits are distinguishable because they are the only
 * `rules` decisions that carry a doc_type.
 */
const describeClassifier = (j: {
  decided_by: string;
  confidence: number | null;
  doc_type: string | null;
}): { label: string; hint: string } => {
  if (j.decided_by === 'ml' && j.confidence != null) {
    return {
      label: `ML (${(j.confidence * 100).toFixed(1)}%)`,
      hint: 'Calibrated model probability above the cascade threshold.',
    };
  }
  if (j.decided_by === 'rules' && j.doc_type) {
    return {
      label: 'PROTOTYPE',
      hint: 'Matched an admin-trained example set by embedding similarity. Similarity is not a calibrated probability, so no percentage is shown.',
    };
  }
  if (j.decided_by === 'rules') {
    return {
      label: 'RULES',
      hint: 'No model or prototype was confident enough; routed to human review.',
    };
  }
  return { label: j.decided_by.toUpperCase(), hint: 'Decided by a human reviewer.' };
};

interface DocumentDrawerProps {
  documentId: string | null;
  onClose: () => void;
  onReclassify?: (doc: DocumentListItem) => void;
}

export const DocumentDrawer: React.FC<DocumentDrawerProps> = ({
  documentId,
  onClose,
  onReclassify,
}) => {
  const [downloading, setDownloading] = useState(false);
  const [openingInBrowser, setOpeningInBrowser] = useState(false);
  const [downloadError, setDownloadError] = useState<unknown>(null);
  const [showPreview, setShowPreview] = useState(false);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!documentId) return;

    const activeElement = document.activeElement as HTMLElement | null;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };

    document.addEventListener('keydown', handleKeyDown);
    document.body.style.overflow = 'hidden';

    closeButtonRef.current?.focus();

    const releaseFocus = panelRef.current ? trapFocus(panelRef.current) : () => {};

    return () => {
      releaseFocus();
      document.removeEventListener('keydown', handleKeyDown);
      document.body.style.overflow = '';
      activeElement?.focus();
    };
  }, [documentId, onClose]);

  const { data: doc, isLoading, error } = useQuery({
    queryKey: ['document', documentId],
    queryFn: () => api.get<DocumentListItem>(`/v1/documents/${documentId}`),
    enabled: !!documentId,
    refetchInterval: (query: any) =>
      query.state?.data?.status === 'processing' ? 2000 : false,
  });

  const { data: findings } = useQuery({
    queryKey: ['document', documentId, 'findings'],
    queryFn: () => api.get<FindingOut[]>(`/v1/documents/${documentId}/findings`),
    enabled: !!documentId,
  });

  const { data: previewData } = useQuery({
    queryKey: ['document', documentId, 'preview'],
    queryFn: () => api.get<DocumentPreviewOut>(`/v1/documents/${documentId}/preview`),
    enabled: !!documentId,
  });

  const { data: jobs } = useQuery({
    queryKey: ['document', documentId, 'jobs'],
    queryFn: () => api.get<JobOut[]>(`/v1/documents/${documentId}/jobs`),
    enabled: !!documentId,
    refetchInterval: doc?.status === 'processing' ? 2000 : false,
  });

  const handleDownload = async () => {
    if (!doc) return;
    try {
      setDownloading(true);
      setDownloadError(null);

      const { blob, filename } = await api.fetchDocumentContent(doc.id);
      let downloadFilename = filename || doc.filename || 'document';
      if (!downloadFilename.includes('.')) {
        if (blob.type === 'application/pdf') {
          downloadFilename += '.pdf';
        } else if (blob.type === 'text/plain') {
          downloadFilename += '.txt';
        } else if (blob.type.includes('wordprocessingml')) {
          downloadFilename += '.docx';
        } else if (blob.type.includes('spreadsheetml')) {
          downloadFilename += '.xlsx';
        }
      }

      const url = window.URL.createObjectURL(blob);
      const a = window.document.createElement('a');
      a.href = url;
      a.download = downloadFilename;
      a.rel = 'noopener';
      window.document.body.appendChild(a);
      a.click();
      window.document.body.removeChild(a);
      setTimeout(() => window.URL.revokeObjectURL(url), 0);
    } catch (err: unknown) {
      setDownloadError(err);
    } finally {
      setDownloading(false);
    }
  };

  const handleOpenInBrowser = async () => {
    if (!doc) return;
    const newWindow = window.open('about:blank', '_blank');
    try {
      setOpeningInBrowser(true);
      setDownloadError(null);

      const { blob } = await api.fetchDocumentView(doc.id);
      const url = window.URL.createObjectURL(blob);
      if (newWindow) {
        newWindow.location.href = url;
      } else {
        window.open(url, '_blank');
      }
      setTimeout(() => window.URL.revokeObjectURL(url), 120000);
    } catch (err: unknown) {
      if (newWindow) {
        newWindow.close();
      }
      setDownloadError(err);
    } finally {
      setOpeningInBrowser(false);
    }
  };

  if (!documentId) return null;

  const displayFindings = previewData?.justification?.findings || findings || [];
  const justification = previewData?.justification;

  return (
    <div 
      className="fixed inset-0 z-50 overflow-hidden bg-[rgba(1,4,9,0.75)] backdrop-blur-2xs animate-in fade-in duration-100"
      role="dialog"
      aria-modal="true"
      aria-labelledby="drawer-title"
    >
      <div className="absolute inset-0" onClick={onClose} aria-hidden="true" />
      <div className="absolute inset-y-0 right-0 max-w-full flex pl-10">
        <div
          ref={panelRef}
          className="w-screen max-w-2xl bg-white dark:bg-[#161b22] border-l border-[#d0d7de] dark:border-[#30363d] shadow-2xl flex flex-col transition-colors"
        >
          {/* Header */}
          <div className="p-4 sm:p-5 border-b border-[#d0d7de] dark:border-[#30363d] flex items-center justify-between bg-[#f6f8fa] dark:bg-[#161b22]">
            <div className="flex items-center gap-2">
              <FileText className="w-4 h-4 text-[#656d76] dark:text-[#848d97]" />
              <h3 id="drawer-title" className="font-semibold text-sm text-[#1f2328] dark:text-[#e6edf3]">
                Document Inspector
              </h3>
            </div>
            <button
              ref={closeButtonRef}
              type="button"
              onClick={onClose}
              aria-label="Close document inspector"
              className="p-1 rounded-sm text-[#656d76] dark:text-[#848d97] hover:text-[#1f2328] dark:hover:text-[#e6edf3] hover:bg-[#eaeef2] dark:hover:bg-[#30363d] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0969da]"
            >
              <X className="w-4 h-4" aria-hidden="true" />
              <span className="sr-only">Close</span>
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

                {doc.duplicate_of && doc.duplicate_of.length > 0 && (
                  <div className="p-3 rounded-md bg-blue-50/50 dark:bg-blue-950/20 border border-blue-200/80 dark:border-blue-900/50 flex gap-2 text-blue-900 dark:text-blue-200">
                    <FileText className="w-4 h-4 shrink-0 mt-0.5" />
                    <div>
                      <p className="text-xs leading-relaxed">
                        This content is identical to {doc.duplicate_of.length} other document(s) in your tenant.
                      </p>
                    </div>
                  </div>
                )}

                {/* Primary Metadata Box */}
                <div className="space-y-3 pb-5 border-b border-[#d8dee4] dark:border-[#30363d]">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <h2 className="text-base font-bold text-[#1f2328] dark:text-[#e6edf3]">
                        {doc.filename}
                      </h2>
                      <p className="text-[11px] font-mono text-[#656d76] dark:text-[#848d97] mt-0.5">
                        ID: {doc.id}
                      </p>
                    </div>
                    <LevelBadge level={doc.level} />
                  </div>

                  <div className="grid grid-cols-2 gap-2 text-xs p-3 bg-[#f6f8fa] dark:bg-[#21262d] rounded-md border border-[#d0d7de] dark:border-[#30363d]">
                    <div>
                      <span className="text-[#656d76] dark:text-[#848d97] block text-[11px]">Type:</span>
                      <span className="font-medium text-[#1f2328] dark:text-[#e6edf3]">
                        {doc.doc_type || 'Unclassified'}
                      </span>
                    </div>
                    {justification?.decided_by && (
                      <div>
                        <span className="text-[#656d76] dark:text-[#848d97] block text-[11px]">Classifier Engine:</span>
                        <span
                          data-testid="classifier-engine"
                          className="font-medium text-[#1f2328] dark:text-[#e6edf3] uppercase text-[10px]"
                          title={describeClassifier(justification).hint}
                        >
                          {describeClassifier(justification).label}
                        </span>
                      </div>
                    )}
                  </div>
                </div>

                {/* Classification Justification & Risk Rationale */}
                {justification?.level_reason && (
                  <div className="p-3.5 bg-blue-50/50 dark:bg-blue-950/20 rounded-md border border-blue-200/80 dark:border-blue-900/50 space-y-1.5">
                    <div className="flex items-center gap-1.5 text-blue-900 dark:text-blue-200 font-semibold text-xs">
                      <ShieldCheck className="w-3.5 h-3.5" />
                      Security Level Justification
                    </div>
                    <p className="text-xs text-blue-950 dark:text-blue-100 leading-relaxed">
                      {justification.level_reason}
                    </p>
                  </div>
                )}

                {/* Classification Actions */}
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <h4 className="font-semibold text-xs text-[#1f2328] dark:text-[#e6edf3] flex items-center gap-1.5">
                      <Cpu className="w-3.5 h-3.5 text-[#0969da] dark:text-[#2f81f7]" />
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

                  {justification?.keywords && justification.keywords.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 pt-1">
                      {justification.keywords.map((kw, i) => (
                        <span
                          key={i}
                          className="px-2 py-0.5 rounded-full text-[11px] bg-[#f6f8fa] dark:bg-[#21262d] border border-[#d0d7de] dark:border-[#30363d] text-[#656d76] dark:text-[#848d97] flex items-center gap-1"
                        >
                          <Tag className="w-2.5 h-2.5" /> #{kw}
                        </span>
                      ))}
                    </div>
                  )}
                </div>

                {/* Sensitive Findings (Invariant #12) */}
                <div className="space-y-2">
                  <h4 className="font-semibold text-xs text-[#1f2328] dark:text-[#e6edf3] flex items-center gap-1.5">
                    <ShieldAlert className="w-3.5 h-3.5 text-[#cf222e] dark:text-[#f85149]" />
                    Sensitive Findings (Offsets Only — Invariant #12)
                  </h4>
                  {displayFindings.length > 0 ? (
                    <div className="space-y-2">
                      {displayFindings.map((f, i) => (
                        <div
                          key={i}
                          className="p-3 bg-white dark:bg-[#0d1117] rounded-md border border-[#d0d7de] dark:border-[#30363d] space-y-1.5 text-xs"
                        >
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                              <span className="font-semibold uppercase text-[10px] tracking-wider px-1.5 py-0.5 rounded bg-[#ffebe9] dark:bg-[#da3633]/25 text-[#cf222e] dark:text-[#f85149] border border-[#ff8182]/30">
                                {f.entity_type.replace('_', ' ')}
                              </span>
                              {(f.page_no != null || f.line_no != null) && (
                                <span className="text-[11px] font-medium text-[#1f2328] dark:text-[#e6edf3]">
                                  Page {f.page_no || 1}{f.line_no ? `, Line ${f.line_no}` : ''}
                                </span>
                              )}
                            </div>
                            <span className="font-mono text-[#656d76] dark:text-[#848d97] text-[11px]">
                              Chars [{f.char_start}..{f.char_end}] • {(f.score * 100).toFixed(0)}% score
                            </span>
                          </div>
                          {f.snippet && (
                            <div className="p-2 bg-[#f6f8fa] dark:bg-[#161b22] rounded border border-[#d0d7de]/60 dark:border-[#30363d]/60 font-mono text-[11px] text-[#1f2328] dark:text-[#e6edf3] break-all">
                              {f.snippet}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-[#656d76] dark:text-[#848d97] text-xs italic">
                      No PII or sensitive patterns detected.
                    </p>
                  )}
                </div>

                {/* Content Text Viewer Toggle */}
                {previewData?.full_text && (
                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <h4 className="font-semibold text-xs text-[#1f2328] dark:text-[#e6edf3] flex items-center gap-1.5">
                        <Eye className="w-3.5 h-3.5 text-[#0969da] dark:text-[#2f81f7]" />
                        Document Content Preview
                      </h4>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setShowPreview(!showPreview)}
                        className="h-6 text-[11px] text-[#0969da] dark:text-[#2f81f7]"
                      >
                        {showPreview ? 'Hide Text' : 'View Text'}
                      </Button>
                    </div>
                    {showPreview && (
                      <div className="p-3 bg-[#f6f8fa] dark:bg-[#0d1117] rounded-md border border-[#d0d7de] dark:border-[#30363d] max-h-60 overflow-y-auto font-mono text-[11px] leading-relaxed whitespace-pre-wrap text-[#1f2328] dark:text-[#e6edf3]">
                        {previewData.full_text}
                      </div>
                    )}
                  </div>
                )}

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
                          className="p-2.5 bg-white dark:bg-[#0d1117] flex flex-col text-xs"
                        >
                          <div className="flex items-center justify-between">
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
                          {j.error && (
                            <div
                              data-testid="job-error"
                              className="mt-1.5 p-2 bg-[#ffebe9] dark:bg-[#490202] text-[#cf222e] dark:text-[#ff7b72] border border-[#ff8182]/40 rounded text-[11px] leading-relaxed break-words"
                            >
                              {j.error}
                            </div>
                          )}
                          {j.attempts > 1 && (
                            <div className="mt-1 text-[10px] text-[#656d76] dark:text-[#848d97]">
                              {j.attempts} attempts
                            </div>
                          )}
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
              <span className="text-[11px] text-[#656d76] dark:text-[#848d97]" data-testid="delivery-mode">
                Delivery: {['confidential', 'restricted'].includes(doc.level ? doc.level.toLowerCase() : '') ? 'API Stream (Range)' : 'Presigned 303'}
              </span>
              <div className="flex items-center gap-2">
                <Can action={Action.PREVIEW} document={doc}>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={handleOpenInBrowser}
                    disabled={openingInBrowser}
                  >
                    <ExternalLink className="w-3.5 h-3.5 mr-1.5" />
                    {openingInBrowser ? 'Opening...' : 'Open in Browser'}
                  </Button>
                </Can>
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

