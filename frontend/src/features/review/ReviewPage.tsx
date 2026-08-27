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
    <div className="space-y-4">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 pb-3 border-b border-[#d0d7de] dark:border-[#30363d]">
        <div>
          <h2 className="text-lg font-bold text-[#1f2328] dark:text-[#e6edf3] tracking-tight flex items-center gap-2">
            <CheckSquare className="w-5 h-5 text-[#656d76] dark:text-[#848d97]" />
            Human Review Queue
          </h2>
          <p className="text-xs text-[#656d76] dark:text-[#848d97] mt-0.5">
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
      <div className="flex items-center gap-1.5 border-b border-[#d0d7de] dark:border-[#30363d] pb-2 text-xs">
        <button
          onClick={() => setStatusFilter('pending')}
          className={`px-3 py-1 rounded-md font-medium transition-colors ${
            statusFilter === 'pending'
              ? 'bg-[#0969da] text-white font-semibold dark:bg-[#1f6feb]'
              : 'text-[#1f2328] dark:text-[#e6edf3] hover:bg-[#f6f8fa] dark:hover:bg-[#21262d]'
          }`}
        >
          Pending Review
        </button>
        <button
          onClick={() => setStatusFilter('resolved')}
          className={`px-3 py-1 rounded-md font-medium transition-colors ${
            statusFilter === 'resolved'
              ? 'bg-[#0969da] text-white font-semibold dark:bg-[#1f6feb]'
              : 'text-[#1f2328] dark:text-[#e6edf3] hover:bg-[#f6f8fa] dark:hover:bg-[#21262d]'
          }`}
        >
          Resolved
        </button>
        <button
          onClick={() => setStatusFilter('')}
          className={`px-3 py-1 rounded-md font-medium transition-colors ${
            statusFilter === ''
              ? 'bg-[#0969da] text-white font-semibold dark:bg-[#1f6feb]'
              : 'text-[#1f2328] dark:text-[#e6edf3] hover:bg-[#f6f8fa] dark:hover:bg-[#21262d]'
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
          icon={<CheckSquare className="w-8 h-8 text-[#1a7f37] dark:text-[#3fb950]" />}
          title="Review queue is clean"
          description="All ingested documents have satisfied automated confidence thresholds or have already been resolved."
        />
      ) : (
        <div className="bg-white dark:bg-[#0d1117] rounded-md border border-[#d0d7de] dark:border-[#30363d] overflow-hidden shadow-2xs transition-colors">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[30%]">Document</TableHead>
                <TableHead>Suggested Level</TableHead>
                <TableHead>Confidence Metrics</TableHead>
                <TableHead className="w-[25%]">Routing Reasons</TableHead>
                <TableHead>Queued At</TableHead>
                <TableHead className="text-right">Action</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((item) => (
                <TableRow key={item.id} className="hover:bg-[#f6f8fa] dark:hover:bg-[#161b22]">
                  <TableCell className="font-semibold text-[#1f2328] dark:text-[#e6edf3]">
                    <div className="flex flex-col">
                      <span className="truncate max-w-xs">{item.title}</span>
                      <span className="text-[10px] text-[#656d76] dark:text-[#848d97] font-mono">
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
                        <div className="flex items-center gap-1.5 text-[#656d76] dark:text-[#848d97]">
                          <span className="text-[10px] text-[#656d76] dark:text-[#848d97] font-medium w-9">Rules:</span>
                          <div className="w-14 bg-[#eaeef2] dark:bg-[#21262d] rounded-full h-1.5 overflow-hidden">
                            <div
                              className="bg-[#0969da] dark:bg-[#2f81f7] h-1.5 rounded-full"
                              style={{ width: `${item.rule_confidence * 100}%` }}
                            />
                          </div>
                          <span className="font-mono text-[10px] text-[#1f2328] dark:text-[#e6edf3]">
                            {(item.rule_confidence * 100).toFixed(0)}%
                          </span>
                        </div>
                      )}
                      {item.ml_confidence !== null && item.ml_confidence !== undefined && (
                        <div className="flex items-center gap-1.5 text-[#656d76] dark:text-[#848d97]">
                          <span className="text-[10px] text-[#656d76] dark:text-[#848d97] font-medium w-9">ML:</span>
                          <div className="w-14 bg-[#eaeef2] dark:bg-[#21262d] rounded-full h-1.5 overflow-hidden">
                            <div
                              className={`h-1.5 rounded-full ${
                                item.ml_confidence >= 0.85
                                  ? 'bg-[#1a7f37] dark:bg-[#3fb950]'
                                  : 'bg-[#9a6700] dark:bg-[#d29922]'
                              }`}
                              style={{ width: `${item.ml_confidence * 100}%` }}
                            />
                          </div>
                          <span className="font-mono text-[10px] text-[#1f2328] dark:text-[#e6edf3]">
                            {(item.ml_confidence * 100).toFixed(0)}%
                          </span>
                        </div>
                      )}
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="space-y-0.5">
                      {item.reasons.map((r, i) => (
                        <div key={i} className="text-[10px] text-[#9a6700] dark:text-[#f2cc60] bg-[#fff8c5] dark:bg-[#9e6a03]/30 px-1.5 py-0.2 rounded border border-[#d4a72c]/40 inline-block mr-1 mb-1 font-mono">
                          {r}
                        </div>
                      ))}
                    </div>
                  </TableCell>
                  <TableCell className="text-[#656d76] dark:text-[#848d97] text-xs">
                    {formatDate(item.created_at)}
                  </TableCell>
                  <TableCell className="text-right">
                    {item.status === 'pending' ? (
                      <Button
                        size="sm"
                        variant="default"
                        onClick={() => setSelectedItem(item)}
                        className="h-6 px-2 text-[11px]"
                      >
                        <CheckSquare className="w-3 h-3 mr-1" />
                        Resolve
                      </Button>
                    ) : (
                      <span className="text-xs font-semibold text-[#656d76] dark:text-[#848d97] capitalize">
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
