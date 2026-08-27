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

export const SearchPage: React.FC = () => {
  const [queryInput, setQueryInput] = useState('');
  const [activeQuery, setActiveQuery] = useState('');
  const [levelFilter, setLevelFilter] = useState<string>('');
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null);

  const {
    data: searchData,
    isLoading,
    error,
    isFetching,
  } = useQuery({
    queryKey: ['search', activeQuery, levelFilter],
    queryFn: () =>
      api.get<SearchResponse>('/v1/search', {
        q: activeQuery,
        security_level: levelFilter || undefined,
        limit: 25,
      }),
    enabled: !!activeQuery,
  });

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (queryInput.trim()) {
      setActiveQuery(queryInput.trim());
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h2 className="text-xl font-bold text-slate-900 tracking-tight">
          Hybrid Search & Candidate Discovery
        </h2>
        <p className="text-xs text-slate-500 mt-0.5">
          Pre-filtered keyword + vector search fused via Reciprocal Rank Fusion ($k=60$).
        </p>
      </div>

      {/* Search Input Bar */}
      <form onSubmit={handleSearchSubmit} className="flex gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
          <Input
            type="text"
            placeholder="Search keywords, contract terms, or taxonomy categories..."
            value={queryInput}
            onChange={(e) => setQueryInput(e.target.value)}
            className="pl-9 h-10 text-sm"
          />
        </div>
        <Button type="submit" disabled={isFetching || !queryInput.trim()} className="h-10 px-5">
          <Sparkles className="w-4 h-4 mr-1.5" />
          {isFetching ? 'Searching...' : 'Search'}
        </Button>
      </form>

      <ProblemAlert error={error} />

      {/* Search Results & Facets */}
      {activeQuery ? (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
          {/* Facets Sidebar (Invariants #27, #28) */}
          <div className="md:col-span-1 space-y-4">
            <div className="p-4 bg-white rounded-lg border border-slate-200 text-xs space-y-3">
              <div className="font-bold text-slate-900 flex items-center gap-1.5 border-b border-slate-100 pb-2">
                <Filter className="w-3.5 h-3.5 text-blue-600" />
                Pre-Filtered Facets
              </div>

              <div>
                <div className="font-semibold text-slate-600 text-[11px] uppercase tracking-wider mb-1.5">
                  Security Level
                </div>
                <div className="space-y-1">
                  <button
                    type="button"
                    onClick={() => setLevelFilter('')}
                    className={`w-full text-left px-2 py-1 rounded flex justify-between items-center ${
                      levelFilter === '' ? 'bg-blue-50 text-blue-700 font-semibold' : 'text-slate-600 hover:bg-slate-50'
                    }`}
                  >
                    <span>All Levels</span>
                    <span>{searchData?.total || 0}</span>
                  </button>
                  {searchData?.facets?.security_levels &&
                    Object.entries(searchData.facets.security_levels).map(([lvl, count]) => (
                      <button
                        key={lvl}
                        type="button"
                        onClick={() => setLevelFilter(lvl)}
                        className={`w-full text-left px-2 py-1 rounded flex justify-between items-center capitalize ${
                          levelFilter === lvl ? 'bg-blue-50 text-blue-700 font-semibold' : 'text-slate-600 hover:bg-slate-50'
                        }`}
                      >
                        <span>{lvl}</span>
                        <span className="font-mono text-slate-400">{count}</span>
                      </button>
                    ))}
                </div>
              </div>

              {searchData?.facets?.doc_types && Object.keys(searchData.facets.doc_types).length > 0 && (
                <div>
                  <div className="font-semibold text-slate-600 text-[11px] uppercase tracking-wider mb-1.5">
                    Document Types
                  </div>
                  <div className="space-y-1">
                    {Object.entries(searchData.facets.doc_types).map(([dt, count]) => (
                      <div key={dt} className="px-2 py-1 text-slate-600 flex justify-between items-center">
                        <span className="truncate">{dt}</span>
                        <span className="font-mono text-slate-400">{count}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Results List */}
          <div className="md:col-span-3 space-y-3">
            {isLoading ? (
              <LoadingSkeleton count={4} />
            ) : searchData?.results && searchData.results.length > 0 ? (
              searchData.results.map((item) => (
                <Card
                  key={item.id}
                  className="cursor-pointer hover:border-blue-300 hover:shadow-xs transition-all"
                  onClick={() => setSelectedDocId(item.id)}
                >
                  <CardContent className="p-4 space-y-2">
                    <div className="flex items-start justify-between gap-3">
                      <div className="space-y-1">
                        <h4 className="font-semibold text-slate-900 text-sm flex items-center gap-2">
                          <FileText className="w-4 h-4 text-blue-600 shrink-0" />
                          <span>{item.title}</span>
                        </h4>
                        <div className="flex items-center gap-2 text-xs text-slate-500">
                          <LevelBadge
                            level={item.security_level_name}
                            rank={item.security_level_rank}
                          />
                          <span>·</span>
                          <span className="font-medium text-slate-700">
                            {item.doc_type_name || 'Unclassified'}
                          </span>
                        </div>
                      </div>
                      <div className="text-right shrink-0">
                        <span className="text-[11px] font-mono px-2 py-0.5 rounded bg-slate-100 text-slate-700 font-semibold">
                          RRF: {item.score ? item.score.toFixed(4) : '—'}
                        </span>
                      </div>
                    </div>

                    {item.snippet && (
                      <p className="text-xs text-slate-600 bg-slate-50 p-2.5 rounded border border-slate-100 font-serif leading-relaxed line-clamp-2">
                        “{item.snippet}”
                      </p>
                    )}
                  </CardContent>
                </Card>
              ))
            ) : (
              <EmptyState
                icon={<Search className="w-10 h-10 text-slate-400" />}
                title="No matching documents"
                description={`No documents matching "${activeQuery}" were found within your current clearance and department view.`}
              />
            )}
          </div>
        </div>
      ) : (
        <EmptyState
          icon={<Search className="w-10 h-10 text-blue-500" />}
          title="Begin your search"
          description="Enter keywords, entity phrases, or document metadata terms above to query the hybrid search index."
        />
      )}

      {/* Drawer */}
      <DocumentDrawer
        documentId={selectedDocId}
        onClose={() => setSelectedDocId(null)}
      />
    </div>
  );
};
