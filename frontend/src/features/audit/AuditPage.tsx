import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import { AuditLogEntry, CursorPaginated } from '../../api/types';
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '../../components/ui/table';
import { Button } from '../../components/ui/button';
import { TableSkeleton } from '../../components/common/LoadingSkeleton';
import { EmptyState } from '../../components/common/EmptyState';
import { ProblemAlert } from '../../components/common/ProblemAlert';
import { formatDate } from '../../lib/utils';
import { History, RefreshCw, User, FileText } from 'lucide-react';

import { useSearchParams } from 'react-router-dom';

export const AuditPage: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const actionFilter = searchParams.get('action') || '';
  
  const [cursors, setCursors] = useState<string[]>([]);
  const currentCursor = cursors[cursors.length - 1] ?? undefined;

  const setActionFilter = (val: string) => {
    const newParams = new URLSearchParams(searchParams);
    if (val) newParams.set('action', val);
    else newParams.delete('action');
    setSearchParams(newParams);
    setCursors([]);
  };

  const {
    data: auditData,
    isLoading,
    error,
    refetch,
    isFetching,
  } = useQuery({
    queryKey: ['audit', actionFilter, currentCursor],
    queryFn: () =>
      api.get<CursorPaginated<AuditLogEntry> | AuditLogEntry[]>('/v1/audit', {
        action: actionFilter || undefined,
        limit: 50,
        cursor: currentCursor,
      }),
  });

  const logs: AuditLogEntry[] = Array.isArray(auditData)
    ? auditData
    : auditData?.items || [];
  const nextCursor = !Array.isArray(auditData) ? auditData?.next_cursor : null;

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 pb-3 border-b border-[#d0d7de] dark:border-[#30363d]">
        <div>
          <h2 className="text-lg font-bold text-[#1f2328] dark:text-[#e6edf3] tracking-tight flex items-center gap-2">
            <History className="w-5 h-5 text-[#656d76] dark:text-[#848d97]" />
            Immutable Audit Trail
          </h2>
          <p className="text-xs text-[#656d76] dark:text-[#848d97] mt-0.5">
            Same-transaction audit logs (Invariant #24 & #30) with database-enforced revocation of UPDATE/DELETE.
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
            Refresh Trail
          </Button>
        </div>
      </div>

      {/* Action Filters */}
      <div className="flex items-center gap-1.5 border-b border-[#d0d7de] dark:border-[#30363d] pb-2 text-xs">
        <button
          onClick={() => setActionFilter('')}
          className={`px-3 py-1 rounded-md font-medium transition-colors ${
            actionFilter === ''
              ? 'bg-[#0969da] text-white font-semibold dark:bg-[#1f6feb]'
              : 'text-[#1f2328] dark:text-[#e6edf3] hover:bg-[#f6f8fa] dark:hover:bg-[#21262d]'
          }`}
        >
          All Actions
        </button>
        <button
          onClick={() => setActionFilter('upload.init')}
          className={`px-3 py-1 rounded-md font-medium transition-colors ${
            actionFilter === 'upload.init'
              ? 'bg-[#0969da] text-white font-semibold dark:bg-[#1f6feb]'
              : 'text-[#1f2328] dark:text-[#e6edf3] hover:bg-[#f6f8fa] dark:hover:bg-[#21262d]'
          }`}
        >
          Uploads
        </button>
        <button
          onClick={() => setActionFilter('reclassify.resolve.human')}
          className={`px-3 py-1 rounded-md font-medium transition-colors ${
            actionFilter === 'reclassify.resolve.human'
              ? 'bg-[#0969da] text-white font-semibold dark:bg-[#1f6feb]'
              : 'text-[#1f2328] dark:text-[#e6edf3] hover:bg-[#f6f8fa] dark:hover:bg-[#21262d]'
          }`}
        >
          Reclassifications
        </button>
        <button
          onClick={() => setActionFilter('download.stream')}
          className={`px-3 py-1 rounded-md font-medium transition-colors ${
            actionFilter === 'download.stream'
              ? 'bg-[#0969da] text-white font-semibold dark:bg-[#1f6feb]'
              : 'text-[#1f2328] dark:text-[#e6edf3] hover:bg-[#f6f8fa] dark:hover:bg-[#21262d]'
          }`}
        >
          Stream Downloads
        </button>
      </div>

      <ProblemAlert error={error} />

      {/* Audit Log Table */}
      {isLoading ? (
        <TableSkeleton rows={8} cols={5} />
      ) : logs.length === 0 ? (
        <EmptyState
          icon={<History className="w-8 h-8 text-[#656d76] dark:text-[#848d97]" />}
          title="No audit entries recorded"
          description="Access events, content downloads, and human classification writes will appear here."
        />
      ) : (
        <div className="bg-white dark:bg-[#0d1117] rounded-md border border-[#d0d7de] dark:border-[#30363d] overflow-hidden shadow-2xs transition-colors">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[20%]">Timestamp</TableHead>
                <TableHead>Action</TableHead>
                <TableHead>Actor Subject</TableHead>
                <TableHead>Document ID</TableHead>
                <TableHead>Details / Context</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {logs.map((log) => (
                <TableRow key={log.id} className="hover:bg-[#f6f8fa] dark:hover:bg-[#161b22] font-mono text-xs">
                  <TableCell className="text-[#656d76] dark:text-[#848d97] font-sans text-xs">
                    {formatDate(log.ts)}
                  </TableCell>
                  <TableCell>
                    <span
                      className={`inline-flex items-center px-1.5 py-0.2 rounded text-[10px] font-semibold border ${
                        log.action.includes('reclassify')
                          ? 'bg-[#fbefff] dark:bg-[#8957e5]/20 text-[#8250df] dark:text-[#a371f7] border-[#d2a8ff]/40'
                          : log.action.includes('download')
                          ? 'bg-[#fff8c5] dark:bg-[#9e6a03]/30 text-[#9a6700] dark:text-[#d29922] border-[#d4a72c]/40'
                          : log.action.includes('upload')
                          ? 'bg-[#ddf4ff] dark:bg-[#388bfd]/20 text-[#0969da] dark:text-[#58a6ff] border-[#54aeff]/40'
                          : 'bg-[#f6f8fa] dark:bg-[#21262d] text-[#1f2328] dark:text-[#e6edf3] border-[#d0d7de] dark:border-[#30363d]'
                      }`}
                    >
                      {log.action}
                    </span>
                  </TableCell>
                  <TableCell className="text-[#1f2328] dark:text-[#e6edf3]">
                    <div className="flex items-center gap-1.5 truncate max-w-[140px]">
                      <User className="w-3 h-3 text-[#656d76] dark:text-[#848d97] shrink-0" />
                      <span className="truncate">{log.actor_id || 'System'}</span>
                    </div>
                  </TableCell>
                  <TableCell className="text-[#656d76] dark:text-[#848d97]">
                    {log.document_id ? (
                      <div className="flex items-center gap-1 truncate max-w-[120px]">
                        <FileText className="w-3 h-3 text-[#656d76] dark:text-[#848d97] shrink-0" />
                        <span className="truncate">{log.document_id.slice(0, 8)}...</span>
                      </div>
                    ) : (
                      <span className="text-[#8c959f] dark:text-[#6e7681]">—</span>
                    )}
                  </TableCell>
                  <TableCell className="text-[#656d76] dark:text-[#848d97] text-[11px] font-mono">
                    <div className="flex flex-col">
                      <span className="truncate max-w-xs">{log.ip || 'No IP'}</span>
                      <span className="truncate max-w-xs text-[#8c959f]">{log.user_agent || 'Unknown agent'}</span>
                    </div>
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
    </div>
  );
};
