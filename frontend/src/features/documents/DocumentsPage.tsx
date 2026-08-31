import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import { DocumentListItem } from '../../api/types';
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '../../components/ui/table';
import { Button } from '../../components/ui/button';
import { LevelBadge } from '../../components/common/LevelBadge';
import { TableSkeleton } from '../../components/common/LoadingSkeleton';
import { EmptyState } from '../../components/common/EmptyState';
import { ProblemAlert } from '../../components/common/ProblemAlert';
import { DocumentDrawer } from './DocumentDrawer';
import { ReclassifyModal } from './ReclassifyModal';
import { formatDate } from '../../lib/utils';
import { FileText, Eye, Filter, RefreshCw, Plus } from 'lucide-react';

import { useSearchParams, useNavigate } from 'react-router-dom';

export const DocumentsPage: React.FC = () => {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const statusFilter = searchParams.get('status') || '';
  const levelFilter = searchParams.get('level') || '';
  
  const [cursors, setCursors] = useState<string[]>([]);
  const currentCursor = cursors[cursors.length - 1] ?? undefined;

  const setStatusFilter = (val: string) => {
    const newParams = new URLSearchParams(searchParams);
    if (val) newParams.set('status', val);
    else newParams.delete('status');
    setSearchParams(newParams);
    setCursors([]); // Reset pagination on filter change
  };

  const setLevelFilter = (val: string) => {
    const newParams = new URLSearchParams(searchParams);
    if (val) newParams.set('level', val);
    else newParams.delete('level');
    setSearchParams(newParams);
    setCursors([]);
  };

  const [selectedDocId, setSelectedDocId] = useState<string | null>(null);
  const [reclassifyingDoc, setReclassifyingDoc] = useState<DocumentListItem | null>(null);

  const {
    data: documentsData,
    isLoading,
    error,
    refetch,
    isFetching,
  } = useQuery({
    queryKey: ['documents', statusFilter, levelFilter, currentCursor],
    queryFn: () =>
      api.get<any>('/v1/documents', {
        status: statusFilter || undefined,
        security_level: levelFilter || undefined,
        limit: 50,
        cursor: currentCursor,
      }),
  });

  const documents: any[] = Array.isArray(documentsData)
    ? documentsData
    : documentsData?.items || [];
  const nextCursor = !Array.isArray(documentsData) ? documentsData?.next_cursor : null;

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 pb-3 border-b border-[#d0d7de] dark:border-[#30363d]">
        <div>
          <h2 className="text-lg font-bold text-[#1f2328] dark:text-[#e6edf3] tracking-tight flex items-center gap-2">
            <FileText className="w-5 h-5 text-[#656d76] dark:text-[#848d97]" />
            Document Repository
          </h2>
          <p className="text-xs text-[#656d76] dark:text-[#848d97] mt-0.5">
            Two-axis permission gated repository with append-only classification logs.
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
          <Button size="sm" variant="default" onClick={() => navigate('/upload')}>
            <Plus className="w-3.5 h-3.5 mr-1" />
            Upload Document
          </Button>
        </div>
      </div>

      {/* Filters Bar */}
      <div className="flex flex-wrap items-center gap-2.5 p-2.5 bg-[#f6f8fa] dark:bg-[#161b22] rounded-md border border-[#d0d7de] dark:border-[#30363d] text-xs transition-colors">
        <div className="flex items-center gap-1.5 text-[#656d76] dark:text-[#848d97] font-semibold">
          <Filter className="w-3.5 h-3.5" />
          <span>Filters:</span>
        </div>

        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="h-7 rounded-md border border-[#d0d7de] dark:border-[#30363d] bg-white dark:bg-[#0d1117] text-[#1f2328] dark:text-[#e6edf3] px-2 text-xs focus:outline-none focus:ring-2 focus:ring-[#0969da]"
        >
          <option value="">Status: All</option>
          <option value="ready">Ready</option>
          <option value="processing">Processing</option>
          <option value="held">Held</option>
          <option value="quarantined">Quarantined</option>
          <option value="failed">Failed</option>
        </select>

        <select
          value={levelFilter}
          onChange={(e) => setLevelFilter(e.target.value)}
          className="h-7 rounded-md border border-[#d0d7de] dark:border-[#30363d] bg-white dark:bg-[#0d1117] text-[#1f2328] dark:text-[#e6edf3] px-2 text-xs focus:outline-none focus:ring-2 focus:ring-[#0969da]"
        >
          <option value="">Security Level: All</option>
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
            className="text-[11px] h-7 text-[#0969da] dark:text-[#58a6ff] hover:underline"
          >
            Clear filters
          </Button>
        )}
      </div>

      <ProblemAlert error={error} />

      {/* Table */}
      {/* A failed request is not an empty repository — see ProblemAlert above. */}
      {isLoading ? (
        <TableSkeleton rows={6} cols={6} />
      ) : error ? null : documents.length === 0 ? (
        <EmptyState
          title="No documents found"
          description={
            statusFilter || levelFilter
              ? 'Try changing or clearing your filters to view documents in this scope.'
              : 'Your repository is empty. Upload your first document to start.'
          }
          actionLabel="Upload Document"
          onAction={() => navigate('/upload')}
        />
      ) : (
        <div className="bg-white dark:bg-[#0d1117] rounded-md border border-[#d0d7de] dark:border-[#30363d] overflow-hidden shadow-2xs transition-colors">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[35%]">Title</TableHead>
                <TableHead>Security Level</TableHead>
                <TableHead>Document Type</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Created</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {documents.map((doc) => (
                <TableRow
                  key={doc.id}
                  className="cursor-pointer hover:bg-[#f6f8fa] dark:hover:bg-[#161b22]"
                  onClick={() => setSelectedDocId(doc.id)}
                >
                  <TableCell className="font-medium">
                    <div className="flex items-center gap-2 text-[#0969da] dark:text-[#2f81f7] hover:underline">
                      <FileText className="w-3.5 h-3.5 text-[#656d76] dark:text-[#848d97] shrink-0" />
                      <span className="truncate max-w-xs">{doc.filename}</span>
                    </div>
                  </TableCell>
                  <TableCell>
                    <LevelBadge
                      level={doc.level}
                    />
                  </TableCell>
                  <TableCell className="text-[#656d76] dark:text-[#848d97] font-medium">
                    {doc.doc_type || 'Unclassified'}
                  </TableCell>
                  <TableCell>
                    <span
                      className={`inline-flex items-center px-1.5 py-0.2 rounded-full text-[10px] font-semibold capitalize border ${
                        doc.status === 'ready'
                          ? 'bg-[#dafbe1] dark:bg-[#238636]/25 text-[#1a7f37] dark:text-[#3fb950] border-[#4ac26b]/40'
                          : doc.status === 'failed'
                          ? 'bg-[#ffebe9] dark:bg-[#da3633]/25 text-[#cf222e] dark:text-[#f85149] border-[#ff8182]/40'
                          : doc.status === 'held'
                          ? 'bg-[#fff8c5] dark:bg-[#9e6a03]/30 text-[#9a6700] dark:text-[#d29922] border-[#d4a72c]/40'
                          : 'bg-[#ddf4ff] dark:bg-[#388bfd]/25 text-[#0969da] dark:text-[#58a6ff] border-[#54aeff]/40'
                      }`}
                    >
                      {doc.status}
                    </span>
                  </TableCell>
                  <TableCell className="text-[#656d76] dark:text-[#848d97] text-xs">
                    {formatDate(doc.created_at)}
                  </TableCell>
                  <TableCell className="text-right" onClick={(e) => e.stopPropagation()}>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setSelectedDocId(doc.id)}
                      className="h-6 px-2 text-[11px]"
                    >
                      <Eye className="w-3 h-3 mr-1" /> View
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Pagination Controls */}
      <div className="flex justify-between items-center pt-2">
        <Button
          variant="outline"
          size="sm"
          onClick={() => setCursors((prev) => prev.slice(0, -1))}
          disabled={cursors.length === 0 || isFetching}
        >
          Previous
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={() => setCursors((prev) => [...prev, nextCursor!])}
          disabled={!nextCursor || isFetching}
        >
          Next
        </Button>
      </div>

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
