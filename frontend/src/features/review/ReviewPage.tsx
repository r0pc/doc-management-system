import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import { ReviewQueueItem, CursorPaginated } from '../../api/types';
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '../../components/ui/table';
import { Button } from '../../components/ui/button';
import { LevelBadge } from '../../components/common/LevelBadge';
import { TableSkeleton } from '../../components/common/LoadingSkeleton';
import { EmptyState } from '../../components/common/EmptyState';
import { ProblemAlert } from '../../components/common/ProblemAlert';
import { ResolveReviewDialog } from './ResolveReviewDialog';
import { formatDate } from '../../lib/utils';
import { CheckSquare, RefreshCw } from 'lucide-react';

export const ReviewPage: React.FC = () => {
  const [statusFilter, setStatusFilter] = useState<string>('pending');
  const [selectedItem, setSelectedItem] = useState<ReviewQueueItem | null>(null);

  const {
    data: reviewData,
    isLoading,
    error,
    refetch,
    isFetching,
  } = useQuery({
    queryKey: ['review', statusFilter],
    queryFn: () =>
      api.get<CursorPaginated<ReviewQueueItem> | ReviewQueueItem[]>('/v1/review', {
        status: statusFilter || undefined,
        limit: 50,
      }),
  });

  const items: ReviewQueueItem[] = Array.isArray(reviewData)
    ? reviewData
    : reviewData?.items || [];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-slate-900 tracking-tight">
            Human Review Queue
          </h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Documents with rule ambiguity or low ML confidence (&lt; 0.85) routed for human verification.
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
            Refresh Queue
          </Button>
        </div>
      </div>

      {/* Filter Tabs */}
      <div className="flex items-center gap-2 border-b border-slate-200 pb-2 text-xs">
        <button
          onClick={() => setStatusFilter('pending')}
          className={`px-3 py-1.5 rounded-lg font-medium transition-colors ${
            statusFilter === 'pending'
              ? 'bg-blue-600 text-white font-semibold shadow-xs'
              : 'text-slate-600 hover:bg-slate-100'
          }`}
        >
          Pending Review
        </button>
        <button
          onClick={() => setStatusFilter('resolved')}
          className={`px-3 py-1.5 rounded-lg font-medium transition-colors ${
            statusFilter === 'resolved'
              ? 'bg-blue-600 text-white font-semibold shadow-xs'
              : 'text-slate-600 hover:bg-slate-100'
          }`}
        >
          Resolved
        </button>
        <button
          onClick={() => setStatusFilter('')}
          className={`px-3 py-1.5 rounded-lg font-medium transition-colors ${
            statusFilter === ''
              ? 'bg-blue-600 text-white font-semibold shadow-xs'
              : 'text-slate-600 hover:bg-slate-100'
          }`}
        >
          All Items
        </button>
      </div>

      <ProblemAlert error={error} />

      {/* Queue Table */}
      {isLoading ? (
        <TableSkeleton rows={5} cols={6} />
      ) : items.length === 0 ? (
        <EmptyState
          icon={<CheckSquare className="w-10 h-10 text-emerald-500" />}
          title="Review queue is clean!"
          description="All ingested documents have satisfied automated confidence thresholds or have already been resolved."
        />
      ) : (
        <div className="bg-white rounded-lg border border-slate-200 overflow-hidden shadow-2xs">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[30%]">Document Title</TableHead>
                <TableHead>Suggested Level</TableHead>
                <TableHead>Confidence Metrics</TableHead>
                <TableHead className="w-[25%]">Routing Reasons</TableHead>
                <TableHead>Queued At</TableHead>
                <TableHead className="text-right">Action</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((item) => (
                <TableRow key={item.id} className="hover:bg-slate-50/60">
                  <TableCell className="font-semibold text-slate-900">
                    <div className="flex flex-col">
                      <span className="truncate max-w-xs">{item.title}</span>
                      <span className="text-[10px] text-slate-400 font-mono">
                        Doc ID: {item.document_id.slice(0, 8)}...
                      </span>
                    </div>
                  </TableCell>
                  <TableCell>
                    <LevelBadge level={item.suggested_level_name} />
                  </TableCell>
                  <TableCell>
                    <div className="space-y-1 text-xs">
                      {item.rule_confidence !== null && item.rule_confidence !== undefined && (
                        <div className="flex items-center gap-1.5 text-slate-600">
                          <span className="text-[10px] text-slate-400 font-medium w-10">Rules:</span>
                          <div className="w-16 bg-slate-100 rounded-full h-1.5 overflow-hidden">
                            <div
                              className="bg-blue-600 h-1.5 rounded-full"
                              style={{ width: `${item.rule_confidence * 100}%` }}
                            />
                          </div>
                          <span className="font-mono text-[10px] text-slate-700">
                            {(item.rule_confidence * 100).toFixed(0)}%
                          </span>
                        </div>
                      )}
                      {item.ml_confidence !== null && item.ml_confidence !== undefined && (
                        <div className="flex items-center gap-1.5 text-slate-600">
                          <span className="text-[10px] text-slate-400 font-medium w-10">ML:</span>
                          <div className="w-16 bg-slate-100 rounded-full h-1.5 overflow-hidden">
                            <div
                              className={`h-1.5 rounded-full ${
                                item.ml_confidence >= 0.85 ? 'bg-emerald-500' : 'bg-amber-500'
                              }`}
                              style={{ width: `${item.ml_confidence * 100}%` }}
                            />
                          </div>
                          <span className="font-mono text-[10px] text-slate-700">
                            {(item.ml_confidence * 100).toFixed(0)}%
                          </span>
                        </div>
                      )}
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="space-y-0.5">
                      {item.reasons.map((r, i) => (
                        <div key={i} className="text-[11px] text-amber-900 bg-amber-50 px-1.5 py-0.5 rounded border border-amber-200/50 inline-block mr-1 mb-1 font-mono">
                          {r}
                        </div>
                      ))}
                    </div>
                  </TableCell>
                  <TableCell className="text-slate-500 text-xs">
                    {formatDate(item.created_at)}
                  </TableCell>
                  <TableCell className="text-right">
                    {item.status === 'pending' ? (
                      <Button
                        size="sm"
                        onClick={() => setSelectedItem(item)}
                        className="h-8 bg-emerald-600 hover:bg-emerald-700 text-white font-medium text-xs shadow-2xs"
                      >
                        <CheckSquare className="w-3.5 h-3.5 mr-1" />
                        Resolve
                      </Button>
                    ) : (
                      <span className="text-xs font-semibold text-slate-400 capitalize">
                        {item.status}
                      </span>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Resolve Dialog */}
      <ResolveReviewDialog
        item={selectedItem}
        onClose={() => setSelectedItem(null)}
      />
    </div>
  );
};
