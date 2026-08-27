import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import { AccessLogOut, CursorPaginated } from '../../api/types';
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '../../components/ui/table';
import { Button } from '../../components/ui/button';
import { TableSkeleton } from '../../components/common/LoadingSkeleton';
import { EmptyState } from '../../components/common/EmptyState';
import { ProblemAlert } from '../../components/common/ProblemAlert';
import { formatDate } from '../../lib/utils';
import { History, RefreshCw, User, FileText } from 'lucide-react';

export const AuditPage: React.FC = () => {
  const [actionFilter, setActionFilter] = useState<string>('');

  const {
    data: auditData,
    isLoading,
    error,
    refetch,
    isFetching,
  } = useQuery({
    queryKey: ['audit', actionFilter],
    queryFn: () =>
      api.get<CursorPaginated<AccessLogOut> | AccessLogOut[]>('/v1/audit', {
        action: actionFilter || undefined,
        limit: 50,
      }),
  });

  const logs: AccessLogOut[] = Array.isArray(auditData)
    ? auditData
    : auditData?.items || [];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-slate-900 tracking-tight">
            Immutable Audit Trail
          </h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Same-transaction audit log (Invariant #24 & #30) with engine-level UPDATE/DELETE revocations.
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
      <div className="flex items-center gap-2 border-b border-slate-200 pb-2 text-xs">
        <button
          onClick={() => setActionFilter('')}
          className={`px-3 py-1.5 rounded-lg font-medium transition-colors ${
            actionFilter === ''
              ? 'bg-blue-600 text-white font-semibold shadow-xs'
              : 'text-slate-600 hover:bg-slate-100'
          }`}
        >
          All Actions
        </button>
        <button
          onClick={() => setActionFilter('upload.init')}
          className={`px-3 py-1.5 rounded-lg font-medium transition-colors ${
            actionFilter === 'upload.init'
              ? 'bg-blue-600 text-white font-semibold shadow-xs'
              : 'text-slate-600 hover:bg-slate-100'
          }`}
        >
          Uploads
        </button>
        <button
          onClick={() => setActionFilter('reclassify.resolve.human')}
          className={`px-3 py-1.5 rounded-lg font-medium transition-colors ${
            actionFilter === 'reclassify.resolve.human'
              ? 'bg-blue-600 text-white font-semibold shadow-xs'
              : 'text-slate-600 hover:bg-slate-100'
          }`}
        >
          Reclassifications
        </button>
        <button
          onClick={() => setActionFilter('download.stream')}
          className={`px-3 py-1.5 rounded-lg font-medium transition-colors ${
            actionFilter === 'download.stream'
              ? 'bg-blue-600 text-white font-semibold shadow-xs'
              : 'text-slate-600 hover:bg-slate-100'
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
          icon={<History className="w-10 h-10 text-slate-400" />}
          title="No audit entries recorded"
          description="Access events, content downloads, and human classification writes will appear here."
        />
      ) : (
        <div className="bg-white rounded-lg border border-slate-200 overflow-hidden shadow-2xs">
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
                <TableRow key={log.id} className="hover:bg-slate-50/60 font-mono text-xs">
                  <TableCell className="text-slate-500 font-sans text-xs">
                    {formatDate(log.created_at)}
                  </TableCell>
                  <TableCell>
                    <span
                      className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold ${
                        log.action.includes('reclassify')
                          ? 'bg-purple-50 text-purple-700 border border-purple-200'
                          : log.action.includes('download')
                          ? 'bg-amber-50 text-amber-700 border border-amber-200'
                          : log.action.includes('upload')
                          ? 'bg-blue-50 text-blue-700 border border-blue-200'
                          : 'bg-slate-100 text-slate-700'
                      }`}
                    >
                      {log.action}
                    </span>
                  </TableCell>
                  <TableCell className="text-slate-700">
                    <div className="flex items-center gap-1.5 truncate max-w-[140px]">
                      <User className="w-3.5 h-3.5 text-slate-400 shrink-0" />
                      <span className="truncate">{log.actor_id || 'System'}</span>
                    </div>
                  </TableCell>
                  <TableCell className="text-slate-600">
                    {log.document_id ? (
                      <div className="flex items-center gap-1 truncate max-w-[120px]">
                        <FileText className="w-3.5 h-3.5 text-slate-400 shrink-0" />
                        <span className="truncate">{log.document_id.slice(0, 8)}...</span>
                      </div>
                    ) : (
                      <span className="text-slate-400">—</span>
                    )}
                  </TableCell>
                  <TableCell className="text-slate-500 text-[11px] font-mono">
                    {log.details ? (
                      <span className="truncate block max-w-xs" title={JSON.stringify(log.details)}>
                        {JSON.stringify(log.details)}
                      </span>
                    ) : (
                      '—'
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
};
