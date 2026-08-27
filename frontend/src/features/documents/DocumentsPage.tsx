import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import { DocumentSummary, DocumentView, CursorPaginated } from '../../api/types';
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '../../components/ui/table';
import { Button } from '../../components/ui/button';
import { LevelBadge } from '../../components/common/LevelBadge';
import { TableSkeleton } from '../../components/common/LoadingSkeleton';
import { EmptyState } from '../../components/common/EmptyState';
import { ProblemAlert } from '../../components/common/ProblemAlert';
import { DocumentDrawer } from './DocumentDrawer';
import { ReclassifyModal } from './ReclassifyModal';
import { formatBytes, formatDate } from '../../lib/utils';
import { FileText, Eye, Filter, RefreshCw } from 'lucide-react';

interface DocumentsPageProps {
  onNavigateUpload?: () => void;
}

export const DocumentsPage: React.FC<DocumentsPageProps> = ({ onNavigateUpload }) => {
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [levelFilter, setLevelFilter] = useState<string>('');
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null);
  const [reclassifyingDoc, setReclassifyingDoc] = useState<DocumentView | null>(null);

  const {
    data: documentsData,
    isLoading,
    error,
    refetch,
    isFetching,
  } = useQuery({
    queryKey: ['documents', statusFilter, levelFilter],
    queryFn: () =>
      api.get<CursorPaginated<DocumentSummary> | DocumentSummary[]>('/v1/documents', {
        status: statusFilter || undefined,
        security_level: levelFilter || undefined,
        limit: 50,
      }),
  });

  // Handle both array and cursor response envelopes
  const documents: DocumentSummary[] = Array.isArray(documentsData)
    ? documentsData
    : documentsData?.items || [];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-slate-900 tracking-tight">
            Document Repository
          </h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Two-axis permission gated library with append-only classification histories.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => refetch()}
            disabled={isFetching}
          >
            <RefreshCw className={`w-3.5 h-3.5 mr-1.5 ${isFetching ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
          {onNavigateUpload && (
            <Button size="sm" onClick={onNavigateUpload}>
              Upload Document
            </Button>
          )}
        </div>
      </div>

      {/* Filters Bar */}
      <div className="flex flex-wrap items-center gap-3 p-3 bg-white rounded-lg border border-slate-200 text-xs">
        <div className="flex items-center gap-1.5 text-slate-500 font-semibold">
          <Filter className="w-3.5 h-3.5" />
          <span>Filters:</span>
        </div>

        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="h-8 rounded-md border border-slate-300 bg-white px-2 text-xs focus:outline-none focus:ring-1 focus:ring-blue-600"
        >
          <option value="">All Statuses</option>
          <option value="ready">Ready</option>
          <option value="processing">Processing</option>
          <option value="quarantined">Quarantined</option>
          <option value="failed">Failed</option>
        </select>

        <select
          value={levelFilter}
          onChange={(e) => setLevelFilter(e.target.value)}
          className="h-8 rounded-md border border-slate-300 bg-white px-2 text-xs focus:outline-none focus:ring-1 focus:ring-blue-600"
        >
          <option value="">All Security Levels</option>
          <option value="public">Public</option>
          <option value="internal">Internal</option>
          <option value="confidential">Confidential</option>
          <option value="restricted">Restricted</option>
        </select>

        {(statusFilter || levelFilter) && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setStatusFilter('');
              setLevelFilter('');
            }}
            className="text-[11px] h-8 text-slate-500 hover:text-slate-900"
          >
            Clear filters
          </Button>
        )}
      </div>

      <ProblemAlert error={error} />

      {/* Table */}
      {isLoading ? (
        <TableSkeleton rows={6} cols={6} />
      ) : documents.length === 0 ? (
        <EmptyState
          title="No documents found"
          description={
            statusFilter || levelFilter
              ? 'Try changing or clearing your filters to see documents.'
              : 'Your repository is empty. Upload your first document to start.'
          }
          actionLabel={onNavigateUpload ? 'Upload Document' : undefined}
          onAction={onNavigateUpload}
        />
      ) : (
        <div className="bg-white rounded-lg border border-slate-200 overflow-hidden shadow-2xs">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[35%]">Document Title</TableHead>
                <TableHead>Security Level</TableHead>
                <TableHead>Document Type</TableHead>
                <TableHead>Size</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Created</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {documents.map((doc) => (
                <TableRow
                  key={doc.id}
                  className="cursor-pointer hover:bg-blue-50/40"
                  onClick={() => setSelectedDocId(doc.id)}
                >
                  <TableCell className="font-semibold text-slate-900">
                    <div className="flex items-center gap-2">
                      <FileText className="w-4 h-4 text-blue-600 shrink-0" />
                      <span className="truncate max-w-xs">{doc.title}</span>
                    </div>
                  </TableCell>
                  <TableCell>
                    <LevelBadge
                      level={doc.security_level_name}
                      rank={doc.security_level_rank}
                    />
                  </TableCell>
                  <TableCell className="text-slate-600 font-medium">
                    {doc.doc_type_name || 'Unclassified'}
                  </TableCell>
                  <TableCell className="font-mono text-slate-500 text-xs">
                    {formatBytes(doc.byte_size || 0)}
                  </TableCell>
                  <TableCell>
                    <span
                      className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-semibold capitalize ${
                        doc.status === 'ready'
                          ? 'bg-emerald-50 text-emerald-700'
                          : doc.status === 'failed'
                          ? 'bg-rose-50 text-rose-700'
                          : 'bg-amber-50 text-amber-700'
                      }`}
                    >
                      {doc.status}
                    </span>
                  </TableCell>
                  <TableCell className="text-slate-500 text-xs">
                    {formatDate(doc.created_at)}
                  </TableCell>
                  <TableCell className="text-right" onClick={(e) => e.stopPropagation()}>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setSelectedDocId(doc.id)}
                      className="h-8 px-2.5 text-xs text-blue-600 hover:text-blue-700"
                    >
                      <Eye className="w-3.5 h-3.5 mr-1" /> View
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Drawer */}
      <DocumentDrawer
        documentId={selectedDocId}
        onClose={() => setSelectedDocId(null)}
        onReclassify={(doc) => {
          setSelectedDocId(null);
          setReclassifyingDoc(doc);
        }}
      />

      {/* Reclassify Modal */}
      <ReclassifyModal
        document={reclassifyingDoc}
        onClose={() => setReclassifyingDoc(null)}
      />
    </div>
  );
};
