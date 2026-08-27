import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import { SearchResponse } from '../../api/types';
import { LevelBadge } from '../../components/common/LevelBadge';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import { Card, CardContent } from '../../components/ui/card';
import { LoadingSkeleton } from '../../components/common/LoadingSkeleton';
import { EmptyState } from '../../components/common/EmptyState';
import { ProblemAlert } from '../../components/common/ProblemAlert';
import { DocumentDrawer } from '../documents/DocumentDrawer';
import { Search, Sparkles, Filter, FileText } from 'lucide-react';

import { useSearchParams } from 'react-router-dom';

export const SearchPage: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const activeQuery = searchParams.get('q') || '';
  const levelFilter = searchParams.get('level') || '';
  
  const [queryInput, setQueryInput] = useState(activeQuery);
  const [cursors, setCursors] = useState<string[]>([]);
  const currentCursor = cursors[cursors.length - 1] ?? undefined;

  const setLevelFilter = (val: string) => {
    const newParams = new URLSearchParams(searchParams);
    if (val) newParams.set('level', val);
    else newParams.delete('level');
    setSearchParams(newParams);
    setCursors([]);
  };

  const [selectedDocId, setSelectedDocId] = useState<string | null>(null);

  const {
    data: searchData,
    isLoading,
    error,
    isFetching,
  } = useQuery({
    queryKey: ['search', activeQuery, levelFilter, currentCursor],
    queryFn: () =>
      api.get<SearchResponse & { next_cursor?: string }>('/v1/search', {
        q: activeQuery,
        security_level: levelFilter || undefined,
        limit: 25,
        cursor: currentCursor,
      }),
    enabled: !!activeQuery,
  });
  const nextCursor = searchData?.next_cursor;

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (queryInput.trim()) {
      const newParams = new URLSearchParams(searchParams);
      newParams.set('q', queryInput.trim());
      setSearchParams(newParams);
      setCursors([]);
    }
  };

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

      <ProblemAlert error={error} />

      {/* Search Results & Facets */}
      {activeQuery ? (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          {/* Facets Sidebar (Invariants #27, #28) */}
          <div className="md:col-span-1 space-y-3">
            <div className="p-3 bg-[#f6f8fa] dark:bg-[#161b22] rounded-md border border-[#d0d7de] dark:border-[#30363d] text-xs space-y-3 transition-colors">
              <div className="font-semibold text-[#1f2328] dark:text-[#e6edf3] flex items-center gap-1.5 border-b border-[#d0d7de] dark:border-[#30363d] pb-2">
                <Filter className="w-3.5 h-3.5 text-[#0969da] dark:text-[#2f81f7]" />
                Pre-Filtered Facets
              </div>

              <div>
                <div className="font-semibold text-[#656d76] dark:text-[#848d97] text-[11px] uppercase tracking-wider mb-1">
                  Security Level
                </div>
                <div className="space-y-0.5">
                  <button
                    type="button"
                    onClick={() => setLevelFilter('')}
                    className={`w-full text-left px-2 py-1 rounded text-xs flex justify-between items-center ${
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
                        onClick={() => setLevelFilter(lvl)}
                        className={`w-full text-left px-2 py-1 rounded text-xs flex justify-between items-center capitalize ${
                          levelFilter === lvl
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

              {searchData?.facets?.doc_types && Object.keys(searchData.facets.doc_types).length > 0 && (
                <div>
                  <div className="font-semibold text-[#656d76] dark:text-[#848d97] text-[11px] uppercase tracking-wider mb-1">
                    Document Types
                  </div>
                  <div className="space-y-0.5">
                    {Object.entries(searchData.facets.doc_types).map(([dt, count]) => (
                      <div key={dt} className="px-2 py-1 text-[#656d76] dark:text-[#848d97] flex justify-between items-center text-xs">
                        <span className="truncate">{dt}</span>
                        <span className="font-mono text-[11px]">{count}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Results List */}
          <div className="md:col-span-3 space-y-2.5">
            {isLoading ? (
              <LoadingSkeleton count={4} />
            ) : searchData?.results && searchData.results.length > 0 ? (
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
                          <LevelBadge
                            level={item.level}
                          />
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
                description={`No documents matching "${activeQuery}" were found within your clearance and department.`}
              />
            )}
          </div>
        </div>
      ) : (
        <EmptyState
          icon={<Search className="w-8 h-8 text-[#0969da] dark:text-[#2f81f7]" />}
          title="Search your repository"
          description="Enter keywords or phrases above to query the combined full-text and vector search index."
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
