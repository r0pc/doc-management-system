import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../../api/client';
import { SecurityLevelOut, DocTypeOut } from '../../api/types';
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '../../components/ui/table';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../../components/ui/card';
import { LevelBadge } from '../../components/common/LevelBadge';
import { TableSkeleton } from '../../components/common/LoadingSkeleton';
import { ProblemAlert } from '../../components/common/ProblemAlert';
import { Shield, FolderTree, Plus, Trash2 } from 'lucide-react';

export const TaxonomyPage: React.FC = () => {
  const queryClient = useQueryClient();

  const [newTypeName, setNewTypeName] = useState('');
  const [newTypeSlug, setNewTypeSlug] = useState('');
  const [newTypeDesc, setNewTypeDesc] = useState('');
  const [error, setError] = useState<any>(null);

  const { data: levels, isLoading: levelsLoading } = useQuery({
    queryKey: ['security-levels'],
    queryFn: () => api.get<SecurityLevelOut[]>('/v1/admin/security-levels'),
  });

  const { data: docTypes, isLoading: docTypesLoading } = useQuery({
    queryKey: ['doc-types'],
    queryFn: () => api.get<DocTypeOut[]>('/v1/admin/doc-types'),
  });

  const createDocTypeMutation = useMutation({
    mutationFn: () =>
      api.post('/v1/admin/doc-types', {
        name: newTypeName,
        slug: newTypeSlug || newTypeName.toLowerCase().replace(/[^a-z0-9]+/g, '-'),
        description: newTypeDesc || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['doc-types'] });
      setNewTypeName('');
      setNewTypeSlug('');
      setNewTypeDesc('');
      setError(null);
    },
    onError: (err) => setError(err),
  });

  const deleteDocTypeMutation = useMutation({
    mutationFn: (id: string) => api.delete(`/v1/admin/doc-types/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['doc-types'] });
    },
    onError: (err) => setError(err),
  });

  const handleCreateType = (e: React.FormEvent) => {
    e.preventDefault();
    if (newTypeName.trim()) {
      createDocTypeMutation.mutate();
    }
  };

  return (
    <div className="space-y-6 max-w-5xl">
      {/* Header */}
      <div className="pb-3 border-b border-[#d0d7de] dark:border-[#30363d]">
        <h2 className="text-lg font-bold text-[#1f2328] dark:text-[#e6edf3] tracking-tight">
          Taxonomy Administration
        </h2>
        <p className="text-xs text-[#656d76] dark:text-[#848d97] mt-0.5">
          Manage system-wide Security Levels hierarchy (Invariant #23: rank ≠ PK) and hierarchical Document Types.
        </p>
      </div>

      <ProblemAlert error={error} />

      {/* 1. Security Levels Table */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Shield className="w-4 h-4 text-[#0969da] dark:text-[#2f81f7]" />
            Security Level Hierarchy
          </CardTitle>
          <CardDescription>
            Strict ordinal rank: `Public` (1) → `Internal` (2) → `Confidential` (3) → `Restricted` (4). Monotonic upward.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {levelsLoading ? (
            <TableSkeleton rows={4} cols={4} />
          ) : (
            <div className="bg-white dark:bg-[#0d1117] rounded-md border border-[#d0d7de] dark:border-[#30363d] overflow-hidden">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-16">Rank</TableHead>
                    <TableHead>Level Label</TableHead>
                    <TableHead>System Identifier / Slug</TableHead>
                    <TableHead>Description</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {levels &&
                    levels.map((lvl) => (
                      <TableRow key={lvl.id}>
                        <TableCell className="font-mono font-bold text-xs text-[#1f2328] dark:text-[#e6edf3]">
                          {lvl.rank}
                        </TableCell>
                        <TableCell>
                          <LevelBadge level={lvl.name} rank={lvl.rank} />
                        </TableCell>
                        <TableCell className="font-mono text-[11px] text-[#656d76] dark:text-[#848d97]">
                          {lvl.name}
                        </TableCell>
                        <TableCell className="text-xs text-[#656d76] dark:text-[#848d97]">
                          {lvl.description || '—'}
                        </TableCell>
                      </TableRow>
                    ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* 2. Document Types CRUD */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FolderTree className="w-4 h-4 text-[#1a7f37] dark:text-[#3fb950]" />
            Document Types (Cascade Hierarchy)
          </CardTitle>
          <CardDescription>
            Categorical taxonomy used by rules and calibrated ML classifier for document cascade matching.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          {/* Create Form */}
          <form onSubmit={handleCreateType} className="p-3.5 bg-[#f6f8fa] dark:bg-[#161b22] border border-[#d0d7de] dark:border-[#30363d] rounded-md space-y-3">
            <div className="font-semibold text-xs text-[#1f2328] dark:text-[#e6edf3]">
              Add New Document Type
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
              <Input
                type="text"
                placeholder="Type Name (e.g. Vendor MSA)"
                value={newTypeName}
                onChange={(e) => setNewTypeName(e.target.value)}
                required
              />
              <Input
                type="text"
                placeholder="Slug (optional, e.g. vendor-msa)"
                value={newTypeSlug}
                onChange={(e) => setNewTypeSlug(e.target.value)}
              />
              <Input
                type="text"
                placeholder="Description / Category"
                value={newTypeDesc}
                onChange={(e) => setNewTypeDesc(e.target.value)}
              />
            </div>
            <div className="flex justify-end">
              <Button
                type="submit"
                variant="default"
                size="sm"
                disabled={createDocTypeMutation.isPending || !newTypeName.trim()}
              >
                <Plus className="w-3.5 h-3.5 mr-1" />
                {createDocTypeMutation.isPending ? 'Adding...' : 'Add Type'}
              </Button>
            </div>
          </form>

          {/* Types List Table */}
          {docTypesLoading ? (
            <TableSkeleton rows={4} cols={4} />
          ) : (
            <div className="bg-white dark:bg-[#0d1117] rounded-md border border-[#d0d7de] dark:border-[#30363d] overflow-hidden">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Type Name</TableHead>
                    <TableHead>Slug</TableHead>
                    <TableHead>Description</TableHead>
                    <TableHead className="text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {docTypes && docTypes.length > 0 ? (
                    docTypes.map((dt) => (
                      <TableRow key={dt.id}>
                        <TableCell className="font-semibold text-xs text-[#1f2328] dark:text-[#e6edf3]">
                          {dt.name}
                        </TableCell>
                        <TableCell className="font-mono text-[11px] text-[#656d76] dark:text-[#848d97]">
                          {dt.slug}
                        </TableCell>
                        <TableCell className="text-xs text-[#656d76] dark:text-[#848d97]">
                          {dt.description || '—'}
                        </TableCell>
                        <TableCell className="text-right">
                          <Button
                            variant="destructive"
                            size="sm"
                            onClick={() => deleteDocTypeMutation.mutate(dt.id)}
                            disabled={deleteDocTypeMutation.isPending}
                            className="h-6 px-2 text-[10px]"
                          >
                            <Trash2 className="w-3 h-3 mr-1" />
                            Delete
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))
                  ) : (
                    <TableRow>
                      <TableCell colSpan={4} className="text-center py-6 text-xs text-[#656d76] dark:text-[#848d97]">
                        No custom document types configured yet.
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
};
