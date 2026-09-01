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
import { ArrowDown, ArrowUp, ArrowUpDown, Building2, Eye, FileText, Filter, Plus, RefreshCw, Sparkles, Trash2 } from 'lucide-react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { usePermissions } from '../../security/usePermissions';
import { Action } from '../../security/permissions';
import { DepartmentPicker } from '../departments/DepartmentPicker';
import { useDepartments, withRoot } from '../departments/useDepartments';

import { useSearchParams, useNavigate } from 'react-router-dom';

export const DocumentsPage: React.FC = () => {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const statusFilter = searchParams.get('status') || '';
  const levelFilter = searchParams.get('level') || '';
  const currentSort = searchParams.get('sort') || 'created_at';
  const currentDirection = (searchParams.get('direction') as 'asc' | 'desc') || 'asc';
  
  const [cursors, setCursors] = useState<string[]>([]);
  const currentCursor = cursors[cursors.length - 1] ?? undefined;

  const { can } = usePermissions();
  const canDelete = can(Action.DELETE);
  const canReclassify = can(Action.RECLASSIFY);
  const canManageDepartments = can(Action.MANAGE_DEPARTMENTS);
  const canSelect = canDelete || canReclassify || canManageDepartments;
  const { data: departments } = useDepartments(canManageDepartments);
  const queryClient = useQueryClient();
  // Selection is keyed by id and scoped to what is currently rendered: paging
  // or filtering clears it, so a "delete 3" can never act on rows the user has
  // since navigated away from and can no longer see.
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [confirming, setConfirming] = useState(false);
  const [deleteError, setDeleteError] = useState<unknown>(null);

  const [departmentsEditing, setDepartmentsEditing] = useState(false);
  const [departmentsError, setDepartmentsError] = useState<unknown>(null);
  const [departmentSelection, setDepartmentSelection] = useState<Set<string>>(new Set());
  const [autoClassifyConfirming, setAutoClassifyConfirming] = useState(false);
  const [autoClassifyError, setAutoClassifyError] = useState<unknown>(null);

  const clearSelection = () => setSelected(new Set());

  const toggleOne = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });


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

  const handleSort = (field: string) => {
    const newParams = new URLSearchParams(searchParams);
    if (currentSort === field) {
      const nextDir = currentDirection === 'asc' ? 'desc' : 'asc';
      newParams.set('direction', nextDir);
    } else {
      newParams.set('sort', field);
      newParams.set('direction', 'asc');
    }
    setSearchParams(newParams);
    setCursors([]);
  };

  const renderSortIndicator = (field: string) => {
    if (currentSort !== field) {
      return <ArrowUpDown className="w-3 h-3 text-[#656d76]/50 dark:text-[#848d97]/50 ml-1 inline-block" />;
    }
    return currentDirection === 'asc' ? (
      <ArrowUp className="w-3 h-3 text-[#0969da] dark:text-[#2f81f7] ml-1 inline-block" />
    ) : (
      <ArrowDown className="w-3 h-3 text-[#0969da] dark:text-[#2f81f7] ml-1 inline-block" />
    );
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
    queryKey: ['documents', statusFilter, levelFilter, currentSort, currentDirection, currentCursor],
    queryFn: () =>
      api.get<any>('/v1/documents', {
        status: statusFilter || undefined,
        security_level: levelFilter || undefined,
        sort: searchParams.get('sort') || undefined,
        direction: searchParams.get('direction') || undefined,
        limit: 50,
        cursor: currentCursor,
      }),
    refetchInterval: (query: any) => {
      const data = query.state?.data;
      if (!data) return false;
      const items = Array.isArray(data) ? data : data.items || [];
      return items.some((doc: any) => doc.status === 'processing') ? 2000 : false;
    },
  });

  const documents: any[] = Array.isArray(documentsData)
    ? documentsData
    : documentsData?.items || [];
  const nextCursor = !Array.isArray(documentsData) ? documentsData?.next_cursor : null;

  // Paging or filtering changes which rows exist; a stale selection would let
  // a confirmed delete act on documents the user can no longer see.
  React.useEffect(() => {
    clearSelection();
  }, [statusFilter, levelFilter, currentSort, currentDirection, currentCursor]);

  const visibleIds = documents.map((d: DocumentListItem) => d.id);
  const selectedVisible = visibleIds.filter((id: string) => selected.has(id));
  const allSelected = visibleIds.length > 0 && selectedVisible.length === visibleIds.length;
  const someSelected = selectedVisible.length > 0 && !allSelected;

  const toggleAll = () =>
    setSelected(allSelected ? new Set() : new Set(visibleIds));

  const deleteMutation = useMutation({
    mutationFn: (ids: string[]) => api.post('/v1/documents/delete', { document_ids: ids }),
    onSuccess: () => {
      setConfirming(false);
      clearSelection();
      queryClient.invalidateQueries({ queryKey: ['documents'] });
    },
    onError: (err: unknown) => {
      // Keep the selection so the user can retry without re-picking rows.
      setConfirming(false);
      setDeleteError(err);
    },
  });

  const departmentsMutation = useMutation({
    mutationFn: (ids: string[]) =>
      api.post('/v1/documents/departments', {
        document_ids: ids,
        // The server adds the root itself and refuses a set without it; sending
        // it explicitly keeps the request honest about what is being stored.
        department_ids: withRoot(departmentSelection, departments),
      }),
    onSuccess: () => {
      setDepartmentsEditing(false);
      clearSelection();
      queryClient.invalidateQueries({ queryKey: ['documents'] });
    },
    onError: (err: unknown) => setDepartmentsError(err),
  });

  const autoClassifyMutation = useMutation({
    mutationFn: (ids: string[]) => api.post('/v1/documents/auto-classify', { document_ids: ids }),
    onSuccess: () => {
      setAutoClassifyConfirming(false);
      clearSelection();
      queryClient.invalidateQueries({ queryKey: ['documents'] });
    },
    onError: (err: unknown) => {
      setAutoClassifyConfirming(false);
      setAutoClassifyError(err);
    },
  });

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

        {canSelect && selectedVisible.length > 0 && (
          <div className="flex items-center gap-2 ml-auto">
            <span className="text-xs text-[#656d76] dark:text-[#848d97]">
              {selectedVisible.length} selected
            </span>
            {canReclassify && (
              <Button
                variant="outline"
                size="sm"
                data-testid="auto-classify-selected"
                onClick={() => setAutoClassifyConfirming(true)}
                className="h-7 px-2 text-[11px] text-[#0969da] dark:text-[#58a6ff] border-[#0969da]/30 hover:bg-[#ddf4ff] dark:hover:bg-[#388bfd]/20"
              >
                <Sparkles className="w-3 h-3 mr-1" /> Auto Classify {selectedVisible.length}
              </Button>
            )}
            {canManageDepartments && (
              <Button
                variant="outline"
                size="sm"
                data-testid="set-departments-selected"
                onClick={() => {
                  setDepartmentsError(null);
                  setDepartmentSelection(new Set());
                  setDepartmentsEditing(true);
                }}
                className="h-7 px-2 text-[11px] text-[#1f2328] dark:text-[#e6edf3]"
              >
                <Building2 className="w-3 h-3 mr-1" /> Departments {selectedVisible.length}
              </Button>
            )}
            {canDelete && (
              <Button
                variant="outline"
                size="sm"
                data-testid="delete-selected"
                onClick={() => setConfirming(true)}
                className="h-7 px-2 text-[11px] text-[#cf222e] dark:text-[#f85149] border-[#ff8182]/50 hover:bg-[#ffebe9] dark:hover:bg-[#da3633]/20"
              >
                <Trash2 className="w-3 h-3 mr-1" /> Delete {selectedVisible.length}
              </Button>
            )}
          </div>
        )}

        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          aria-label="Status"
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
          aria-label="Security Level"
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
          <Table data-testid="documents-table">
            <TableHeader>
              <TableRow>
                {canSelect && (
                  <TableHead className="w-8">
                    <input
                      type="checkbox"
                      data-testid="select-all"
                      aria-label="Select all documents on this page"
                      className="cursor-pointer align-middle"
                      checked={allSelected}
                      ref={(el) => {
                        // Indeterminate is not an attribute — it only exists as
                        // a DOM property, so it has to be set on the node.
                        if (el) el.indeterminate = someSelected;
                      }}
                      onChange={toggleAll}
                    />
                  </TableHead>
                )}
                <TableHead className="w-[35%]">
                  <button
                    type="button"
                    onClick={() => handleSort('filename')}
                    className="flex items-center gap-1 font-semibold text-xs text-[#1f2328] dark:text-[#e6edf3] hover:text-[#0969da] dark:hover:text-[#2f81f7] cursor-pointer"
                  >
                    Title {renderSortIndicator('filename')}
                  </button>
                </TableHead>
                <TableHead>
                  <button
                    type="button"
                    onClick={() => handleSort('level')}
                    className="flex items-center gap-1 font-semibold text-xs text-[#1f2328] dark:text-[#e6edf3] hover:text-[#0969da] dark:hover:text-[#2f81f7] cursor-pointer"
                  >
                    Security Level {renderSortIndicator('level')}
                  </button>
                </TableHead>
                <TableHead>
                  <button
                    type="button"
                    onClick={() => handleSort('doc_type')}
                    className="flex items-center gap-1 font-semibold text-xs text-[#1f2328] dark:text-[#e6edf3] hover:text-[#0969da] dark:hover:text-[#2f81f7] cursor-pointer"
                  >
                    Document Type {renderSortIndicator('doc_type')}
                  </button>
                </TableHead>
                <TableHead>
                  <button
                    type="button"
                    onClick={() => handleSort('status')}
                    className="flex items-center gap-1 font-semibold text-xs text-[#1f2328] dark:text-[#e6edf3] hover:text-[#0969da] dark:hover:text-[#2f81f7] cursor-pointer"
                  >
                    Status {renderSortIndicator('status')}
                  </button>
                </TableHead>
                <TableHead>
                  <button
                    type="button"
                    onClick={() => handleSort('created_at')}
                    className="flex items-center gap-1 font-semibold text-xs text-[#1f2328] dark:text-[#e6edf3] hover:text-[#0969da] dark:hover:text-[#2f81f7] cursor-pointer"
                  >
                    Created {renderSortIndicator('created_at')}
                  </button>
                </TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {documents.map((doc) => (
                <TableRow
                  key={doc.id}
                  data-testid="document-row"
                  data-filename={doc.filename}
                  data-status={doc.status}
                  className="cursor-pointer hover:bg-[#f6f8fa] dark:hover:bg-[#161b22]"
                  onClick={() => setSelectedDocId(doc.id)}
                >
                  {canSelect && (
                    // stopPropagation: the row opens the drawer on click, and
                    // ticking a checkbox must not also open it.
                    <TableCell className="w-8" onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        data-testid="row-select"
                        aria-label={`Select ${doc.filename}`}
                        className="cursor-pointer align-middle"
                        checked={selected.has(doc.id)}
                        onChange={() => toggleOne(doc.id)}
                      />
                    </TableCell>
                  )}
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
      {confirming && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-[rgba(1,4,9,0.75)] p-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="confirm-delete-title"
        >
          <div className="w-full max-w-md rounded-md border border-[#d0d7de] dark:border-[#30363d] bg-white dark:bg-[#161b22] p-5 shadow-2xl">
            <h2
              id="confirm-delete-title"
              className="text-sm font-semibold text-[#1f2328] dark:text-[#e6edf3]"
            >
              Delete {selectedVisible.length} document
              {selectedVisible.length === 1 ? '' : 's'}?
            </h2>
            <p className="mt-2 text-xs text-[#656d76] dark:text-[#848d97]">
              They stop appearing in listings, search and review. The audit
              trail and classification history are retained, so this is
              recorded rather than erased — but there is no undo in the UI.
            </p>
            {deleteError != null && (
              <div className="mt-3">
                <ProblemAlert error={deleteError} />
              </div>
            )}
            <div className="mt-4 flex justify-end gap-2">
              <Button
                variant="outline"
                size="sm"
                data-testid="cancel-delete"
                onClick={() => setConfirming(false)}
                className="h-7 px-3 text-[11px]"
              >
                Cancel
              </Button>
              <Button
                size="sm"
                data-testid="confirm-delete"
                disabled={deleteMutation.isPending}
                onClick={() => {
                  setDeleteError(null);
                  deleteMutation.mutate(selectedVisible);
                }}
                className="h-7 px-3 text-[11px] bg-[#cf222e] hover:bg-[#a40e26] text-white"
              >
                {deleteMutation.isPending ? 'Deleting…' : 'Delete'}
              </Button>
            </div>
          </div>
        </div>
      )}

      {departmentsEditing && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-[rgba(1,4,9,0.75)] p-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="set-departments-title"
        >
          <div className="w-full max-w-md rounded-md border border-[#d0d7de] dark:border-[#30363d] bg-white dark:bg-[#161b22] p-5 shadow-2xl">
            <h2
              id="set-departments-title"
              className="text-sm font-semibold text-[#1f2328] dark:text-[#e6edf3]"
            >
              Set departments for {selectedVisible.length} document
              {selectedVisible.length === 1 ? '' : 's'}
            </h2>
            <p className="mt-2 mb-3 text-xs text-[#656d76] dark:text-[#848d97]">
              Everyone in a selected department&apos;s subtree will be able to see these
              documents, subject to their clearance. This replaces the current
              departments rather than adding to them.
            </p>
            <DepartmentPicker
              selected={departmentSelection}
              onChange={setDepartmentSelection}
              disabled={departmentsMutation.isPending}
            />
            {departmentsError != null && (
              <div className="mt-3">
                <ProblemAlert error={departmentsError} />
              </div>
            )}
            <div className="mt-4 flex justify-end gap-2">
              <Button
                variant="outline"
                size="sm"
                data-testid="cancel-set-departments"
                onClick={() => setDepartmentsEditing(false)}
                className="h-7 px-3 text-[11px]"
              >
                Cancel
              </Button>
              <Button
                size="sm"
                data-testid="confirm-set-departments"
                disabled={departmentsMutation.isPending}
                onClick={() => {
                  setDepartmentsError(null);
                  departmentsMutation.mutate(selectedVisible);
                }}
                className="h-7 px-3 text-[11px]"
              >
                {departmentsMutation.isPending ? 'Saving…' : 'Save'}
              </Button>
            </div>
          </div>
        </div>
      )}

      {autoClassifyConfirming && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-[rgba(1,4,9,0.75)] p-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="confirm-auto-classify-title"
        >
          <div className="w-full max-w-md rounded-md border border-[#d0d7de] dark:border-[#30363d] bg-white dark:bg-[#161b22] p-5 shadow-2xl">
            <h2
              id="confirm-auto-classify-title"
              className="text-sm font-semibold text-[#1f2328] dark:text-[#e6edf3]"
            >
              Auto-classify {selectedVisible.length} document
              {selectedVisible.length === 1 ? '' : 's'}?
            </h2>
            <p className="mt-2 text-xs text-[#656d76] dark:text-[#848d97]">
              The automated classification pipeline will re-evaluate the selected documents
              against current detector rules, ML models, and taxonomy. Security levels will not be lowered.
            </p>
            {autoClassifyError != null && (
              <div className="mt-3">
                <ProblemAlert error={autoClassifyError} />
              </div>
            )}
            <div className="mt-4 flex justify-end gap-2">
              <Button
                variant="outline"
                size="sm"
                data-testid="cancel-auto-classify"
                onClick={() => setAutoClassifyConfirming(false)}
                className="h-7 px-3 text-[11px]"
              >
                Cancel
              </Button>
              <Button
                size="sm"
                data-testid="confirm-auto-classify"
                disabled={autoClassifyMutation.isPending}
                onClick={() => {
                  setAutoClassifyError(null);
                  autoClassifyMutation.mutate(selectedVisible);
                }}
                className="h-7 px-3 text-[11px] bg-[#0969da] hover:bg-[#0854ad] text-white"
              >
                {autoClassifyMutation.isPending ? 'Classifying…' : 'Auto Classify'}
              </Button>
            </div>
          </div>
        </div>
      )}

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
