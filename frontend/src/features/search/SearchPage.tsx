import React, { useState, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import { api } from '../../api/client';
import { SearchResponse, DocTypeOut } from '../../api/types';
import { LevelBadge } from '../../components/common/LevelBadge';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import { Card, CardContent } from '../../components/ui/card';
import { LoadingSkeleton } from '../../components/common/LoadingSkeleton';
import { EmptyState } from '../../components/common/EmptyState';
import { ProblemAlert } from '../../components/common/ProblemAlert';
import { DocumentDrawer } from '../documents/DocumentDrawer';
import { useDepartments } from '../departments/useDepartments';
import { usePermissions } from '../../security/usePermissions';
import { Action } from '../../security/permissions';
import { Search, Sparkles, Filter, FileText, Building2, X } from 'lucide-react';

const DEFAULT_DOC_TYPES = [
  'Contract',
  'Vendor MSA',
  'Financial Statement',
  'Invoice',
  'Policy Memo',
  'HR Letter',
  'Disciplinary Notice',
  'Report',
  'SEC 10-Q Report',
];

export const SearchPage: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const activeQuery = searchParams.get('q') || '';
  const levelFilter = searchParams.get('level') || '';
  const docTypeFilter = searchParams.get('doc_type') || '';
  const departmentFilter = searchParams.get('department_id') || '';

  const { can } = usePermissions();
  const canManageDepartments = can(Action.MANAGE_DEPARTMENTS);
  const canManageTaxonomy = can(Action.MANAGE_TAXONOMY);

  const { data: departments } = useDepartments(canManageDepartments);

  const { data: taxonomyDocTypes } = useQuery({
    queryKey: ['doc-types'],
    queryFn: () => api.get<DocTypeOut[]>('/v1/admin/doc-types'),
    enabled: canManageTaxonomy,
    staleTime: 5 * 60 * 1000,
    retry: false,
  });

  const [queryInput, setQueryInput] = useState(activeQuery);
  const [cursors, setCursors] = useState<string[]>([]);
  const currentCursor = cursors[cursors.length - 1] ?? undefined;
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null);

  // Sync local input when URL q param changes
  React.useEffect(() => {
    setQueryInput(activeQuery);
  }, [activeQuery]);

  const updateFilters = (updates: {
    q?: string;
    level?: string;
    doc_type?: string;
    department_id?: string;
  }) => {
    const newParams = new URLSearchParams(searchParams);
    if (updates.q !== undefined) {
      if (updates.q.trim()) newParams.set('q', updates.q.trim());
      else newParams.delete('q');
    }
    if (updates.level !== undefined) {
      if (updates.level) newParams.set('level', updates.level.toLowerCase());
      else newParams.delete('level');
    }
    if (updates.doc_type !== undefined) {
      if (updates.doc_type) newParams.set('doc_type', updates.doc_type);
      else newParams.delete('doc_type');
    }
    if (updates.department_id !== undefined) {
      if (updates.department_id) newParams.set('department_id', updates.department_id);
      else newParams.delete('department_id');
    }
    setSearchParams(newParams);
    setCursors([]);
  };

  const clearAllFilters = () => {
    setSearchParams(new URLSearchParams());
    setQueryInput('');
    setCursors([]);
  };

  const {
    data: searchData,
    isLoading,
    error,
    isFetching,
  } = useQuery({
    queryKey: ['search', activeQuery, levelFilter, docTypeFilter, departmentFilter, currentCursor],
    queryFn: () =>
      api.get<SearchResponse & { next_cursor?: string }>('/v1/search', {
        q: activeQuery,
        level: levelFilter ? levelFilter.toLowerCase() : undefined,
        doc_type: docTypeFilter || undefined,
        department_id: departmentFilter || undefined,
        limit: 25,
        cursor: currentCursor,
      }),
    enabled: !!activeQuery,
  });
  const nextCursor = searchData?.next_cursor;

  const availableDocTypes = useMemo(() => {
    const set = new Set<string>(DEFAULT_DOC_TYPES);
    if (taxonomyDocTypes) {
      for (const dt of taxonomyDocTypes) {
        if (dt.name) set.add(dt.name);
      }
    }
    if (searchData?.facets?.doc_types) {
      for (const name of Object.keys(searchData.facets.doc_types)) {
        if (name && name !== 'unknown') set.add(name);
      }
    }
    return Array.from(set).sort();
  }, [taxonomyDocTypes, searchData?.facets?.doc_types]);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (queryInput.trim()) {
      updateFilters({ q: queryInput });
    }
  };

  const hasActiveFilters = Boolean(
    activeQuery || levelFilter || docTypeFilter || departmentFilter
  );

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="pb-3 border-b border-[#d0d7de] dark:border-[#30363d]">
        <h2 className="text-lg font-bold text-[#1f2328] dark:text-[#e6edf3] tracking-tight flex items-center gap-2">
          <Search className="w-5 h-5 text-[#656d76] dark:text-[#848d97]" />
          Hybrid Search & Discovery
        </h2>
        <p className="text-xs text-[#656d76] dark:text-[#848d97] mt-0.5">
          Pre-filtered keyword + vector search fused via Reciprocal Rank Fusion ($k=60$).
        </p>
      </div>

      {/* Search Input Bar */}
      <form onSubmit={handleSearchSubmit} className="flex gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-2.5 top-2 h-4 w-4 text-[#656d76] dark:text-[#848d97]" />
          <Input
            type="text"
            placeholder="Search documents by keywords, content, or entity names..."
            value={queryInput}
            onChange={(e) => setQueryInput(e.target.value)}
            className="pl-8 h-8 text-xs"
            aria-label="Search query"
          />
        </div>
        <Button
          type="submit"
          variant="default"
          disabled={isFetching || !queryInput.trim()}
          className="h-8 px-3"
        >
          <Sparkles className="w-3.5 h-3.5 mr-1" />
          {isFetching ? 'Searching...' : 'Search'}
        </Button>
      </form>

      {/* Filters Toolbar (Always visible, before and after searching) */}
      <div className="flex flex-wrap items-center gap-2.5 p-2.5 bg-[#f6f8fa] dark:bg-[#161b22] rounded-md border border-[#d0d7de] dark:border-[#30363d] text-xs transition-colors">
        <div className="flex items-center gap-1.5 text-[#656d76] dark:text-[#848d97] font-semibold">
          <Filter className="w-3.5 h-3.5" />
          <span>Filters:</span>
        </div>

        {/* Security Level Dropdown */}
        <select
          value={levelFilter}
          onChange={(e) => updateFilters({ level: e.target.value })}
          aria-label="Security Level"
          data-testid="search-filter-level"
          className="h-7 rounded-md border border-[#d0d7de] dark:border-[#30363d] bg-white dark:bg-[#0d1117] text-[#1f2328] dark:text-[#e6edf3] px-2 text-xs focus:outline-none focus:ring-2 focus:ring-[#0969da]"
        >
          <option value="">Security Level: All</option>
          <option value="public">Public</option>
          <option value="internal">Internal</option>
          <option value="confidential">Confidential</option>
          <option value="restricted">Restricted</option>
        </select>

        {/* Document Type Dropdown */}
        <select
          value={docTypeFilter}
          onChange={(e) => updateFilters({ doc_type: e.target.value })}
          aria-label="Document Type"
          data-testid="search-filter-doctype"
          className="h-7 rounded-md border border-[#d0d7de] dark:border-[#30363d] bg-white dark:bg-[#0d1117] text-[#1f2328] dark:text-[#e6edf3] px-2 text-xs focus:outline-none focus:ring-2 focus:ring-[#0969da]"
        >
          <option value="">Document Type: All</option>
          {availableDocTypes.map((dt) => (
            <option key={dt} value={dt}>
              {dt}
            </option>
          ))}
        </select>

        {/* Department Dropdown (for Admin / Department Manager) */}
        {canManageDepartments && departments && departments.length > 0 && (
          <select
            value={departmentFilter}
            onChange={(e) => updateFilters({ department_id: e.target.value })}
            aria-label="Department"
            data-testid="search-filter-department"
            className="h-7 rounded-md border border-[#d0d7de] dark:border-[#30363d] bg-white dark:bg-[#0d1117] text-[#1f2328] dark:text-[#e6edf3] px-2 text-xs focus:outline-none focus:ring-2 focus:ring-[#0969da]"
          >
            <option value="">Department: All</option>
            {departments.map((dept) => (
              <option key={dept.id} value={dept.id}>
                {dept.name} {dept.is_root ? '(Root)' : ''}
              </option>
            ))}
          </select>
        )}

        {/* Clear Filters Button */}
        {hasActiveFilters && (
          <Button
            variant="ghost"
            size="sm"
            onClick={clearAllFilters}
            data-testid="search-clear-filters"
            className="h-7 px-2 text-[11px] text-[#656d76] dark:text-[#848d97] hover:text-[#cf222e] dark:hover:text-[#f85149]"
          >
            <X className="w-3 h-3 mr-1" />
            Clear Filters
          </Button>
        )}
      </div>

      <ProblemAlert error={error} />

      {/* Search Results & Facets */}
      {activeQuery ? (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          {/* Facets Sidebar (Invariants #27, #28) */}
          <div className="md:col-span-1 space-y-3">
            <div className="p-3 bg-[#f6f8fa] dark:bg-[#161b22] rounded-md border border-[#d0d7de] dark:border-[#30363d] text-xs space-y-3 transition-colors">
              <div className="font-semibold text-[#1f2328] dark:text-[#e6edf3] flex items-center justify-between border-b border-[#d0d7de] dark:border-[#30363d] pb-2">
                <div className="flex items-center gap-1.5">
                  <Filter className="w-3.5 h-3.5 text-[#0969da] dark:text-[#2f81f7]" />
                  <span>Pre-Filtered Facets</span>
                </div>
                {(levelFilter || docTypeFilter || departmentFilter) && (
                  <button
                    type="button"
                    onClick={() => updateFilters({ level: '', doc_type: '', department_id: '' })}
                    className="text-[10px] text-[#0969da] dark:text-[#58a6ff] hover:underline"
                  >
                    Reset
                  </button>
                )}
              </div>

              {/* Security Level Facet */}
              <div>
                <div className="font-semibold text-[#656d76] dark:text-[#848d97] text-[11px] uppercase tracking-wider mb-1">
                  Security Level
                </div>
                <div className="space-y-0.5">
                  <button
                    type="button"
                    onClick={() => updateFilters({ level: '' })}
                    className={`w-full text-left px-2 py-1 rounded text-xs flex justify-between items-center transition-colors ${
                      levelFilter === ''
                        ? 'bg-[#0969da] text-white font-semibold dark:bg-[#1f6feb]'
                        : 'text-[#1f2328] dark:text-[#e6edf3] hover:bg-[#eaeef2] dark:hover:bg-[#21262d]'
                    }`}
                  >
                    <span>All Levels</span>
                    <span className="font-mono text-[11px]">{searchData?.total_candidates || 0}</span>
                  </button>
                  {searchData?.facets?.levels &&
                    Object.entries(searchData.facets.levels).map(([lvl, count]) => (
                      <button
                        key={lvl}
                        type="button"
                        onClick={() => updateFilters({ level: lvl })}
                        className={`w-full text-left px-2 py-1 rounded text-xs flex justify-between items-center capitalize transition-colors ${
                          levelFilter.toLowerCase() === lvl.toLowerCase()
                            ? 'bg-[#0969da] text-white font-semibold dark:bg-[#1f6feb]'
                            : 'text-[#1f2328] dark:text-[#e6edf3] hover:bg-[#eaeef2] dark:hover:bg-[#21262d]'
                        }`}
                      >
                        <span>{lvl}</span>
                        <span className="font-mono text-[11px] opacity-75">{count}</span>
                      </button>
                    ))}
                </div>
              </div>

              {/* Document Type Facet */}
              {searchData?.facets?.doc_types && Object.keys(searchData.facets.doc_types).length > 0 && (
                <div>
                  <div className="font-semibold text-[#656d76] dark:text-[#848d97] text-[11px] uppercase tracking-wider mb-1">
                    Document Types
                  </div>
                  <div className="space-y-0.5">
                    <button
                      type="button"
                      onClick={() => updateFilters({ doc_type: '' })}
                      className={`w-full text-left px-2 py-1 rounded text-xs flex justify-between items-center transition-colors ${
                        docTypeFilter === ''
                          ? 'bg-[#0969da] text-white font-semibold dark:bg-[#1f6feb]'
                          : 'text-[#1f2328] dark:text-[#e6edf3] hover:bg-[#eaeef2] dark:hover:bg-[#21262d]'
                      }`}
                    >
                      <span>All Types</span>
                      <span className="font-mono text-[11px]">{searchData?.total_candidates || 0}</span>
                    </button>
                    {Object.entries(searchData.facets.doc_types).map(([dt, count]) => (
                      <button
                        key={dt}
                        type="button"
                        onClick={() => updateFilters({ doc_type: dt === 'unknown' ? '' : dt })}
                        className={`w-full text-left px-2 py-1 rounded text-xs flex justify-between items-center transition-colors ${
                          docTypeFilter === dt
                            ? 'bg-[#0969da] text-white font-semibold dark:bg-[#1f6feb]'
                            : 'text-[#1f2328] dark:text-[#e6edf3] hover:bg-[#eaeef2] dark:hover:bg-[#21262d]'
                        }`}
                      >
                        <span className="truncate">{dt === 'unknown' ? 'Unclassified' : dt}</span>
                        <span className="font-mono text-[11px] opacity-75">{count}</span>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Department Facet Indicator (for Admin) */}
              {canManageDepartments && departmentFilter && departments && (
                <div className="pt-1 border-t border-[#d0d7de] dark:border-[#30363d]">
                  <div className="font-semibold text-[#656d76] dark:text-[#848d97] text-[11px] uppercase tracking-wider mb-1 flex items-center gap-1">
                    <Building2 className="w-3 h-3" />
                    <span>Department Filter</span>
                  </div>
                  <div className="flex items-center justify-between p-1.5 bg-white dark:bg-[#0d1117] rounded border border-[#d0d7de] dark:border-[#30363d]">
                    <span className="truncate text-[11px] font-medium text-[#0969da] dark:text-[#58a6ff]">
                      {departments.find((d) => d.id === departmentFilter)?.name || 'Filtered'}
                    </span>
                    <button
                      type="button"
                      onClick={() => updateFilters({ department_id: '' })}
                      className="text-[#656d76] hover:text-[#cf222e] p-0.5"
                      aria-label="Remove department filter"
                    >
                      <X className="w-3 h-3" />
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Results List */}
          <div className="md:col-span-3 space-y-2.5">
            {/*
              An API failure is NOT an empty result: saying "no documents match
              within your clearance" when the request was actually denied or
              broken is the most misleading thing a permission-scoped list can
              say. ProblemAlert above owns the error.
            */}
            {isLoading ? (
              <LoadingSkeleton count={4} />
            ) : error ? null : searchData?.results && searchData.results.length > 0 ? (
              searchData.results.map((item) => (
                <Card
                  key={item.document_id}
                  className="cursor-pointer hover:border-[#0969da] dark:hover:border-[#2f81f7] transition-all"
                  onClick={() => setSelectedDocId(item.document_id)}
                >
                  <CardContent className="p-3.5 space-y-2">
                    <div className="flex items-start justify-between gap-3">
                      <div className="space-y-0.5">
                        <h4 className="font-semibold text-xs text-[#0969da] dark:text-[#2f81f7] hover:underline flex items-center gap-1.5">
                          <FileText className="w-3.5 h-3.5 text-[#656d76] dark:text-[#848d97] shrink-0" />
                          <span>{item.filename}</span>
                        </h4>
                        <div className="flex items-center gap-2 text-[11px] text-[#656d76] dark:text-[#848d97]">
                          <LevelBadge level={item.level} />
                          <span>·</span>
                          <span className="font-medium text-[#1f2328] dark:text-[#e6edf3]">
                            {item.doc_type || 'Unclassified'}
                          </span>
                        </div>
                      </div>
                      <div className="text-right shrink-0">
                        <span className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-[#f6f8fa] dark:bg-[#21262d] text-[#656d76] dark:text-[#848d97] font-semibold border border-[#d0d7de] dark:border-[#30363d]">
                          RRF: {item.score ? item.score.toFixed(4) : '—'}
                        </span>
                      </div>
                    </div>

                    {item.snippet && (
                      <p className="text-xs text-[#1f2328] dark:text-[#e6edf3] bg-[#f6f8fa] dark:bg-[#161b22] p-2 rounded border border-[#d8dee4] dark:border-[#30363d] leading-relaxed line-clamp-2">
                        “{item.snippet}”
                      </p>
                    )}
                  </CardContent>
                </Card>
              ))
            ) : (
              <EmptyState
                icon={<Search className="w-8 h-8 text-[#656d76] dark:text-[#848d97]" />}
                title="No matching documents"
                description={`No documents matching "${activeQuery}" were found within your clearance, department, and filters.`}
              />
            )}
          </div>
        </div>
      ) : (
        <EmptyState
          icon={<Search className="w-8 h-8 text-[#0969da] dark:text-[#2f81f7]" />}
          title="Search your repository"
          description="Enter keywords or phrases above and configure filters to query the combined full-text and vector search index."
        />
      )}

      {/* Drawer */}
      <DocumentDrawer
        documentId={selectedDocId}
        onClose={() => setSelectedDocId(null)}
      />

      {/* Pagination Controls */}
      {activeQuery && searchData && (
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
      )}
    </div>
  );
};

