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
    <div className="space-y-8 max-w-5xl">
      {/* Header */}
      <div>
        <h2 className="text-xl font-bold text-slate-900 tracking-tight">
          Taxonomy & Security Governance
        </h2>
        <p className="text-xs text-slate-500 mt-0.5">
          Manage monotonic security levels and hierarchical document categories.
        </p>
      </div>

      <ProblemAlert error={error} />

      {/* Security Levels Reference */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Shield className="w-5 h-5 text-blue-600" />
            Security Level Hierarchy
          </CardTitle>
          <CardDescription>
            Monotonic upward aggregation (Invariant #8 & #23). Absence of evidence defaults to Internal (Rank 2).
          </CardDescription>
        </CardHeader>
        <CardContent>
          {levelsLoading ? (
            <TableSkeleton rows={4} cols={3} />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-20">Rank</TableHead>
                  <TableHead>Level Name</TableHead>
                  <TableHead>Description / Access Boundary</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {levels?.map((lvl) => (
                  <TableRow key={lvl.id}>
                    <TableCell className="font-mono font-bold text-slate-900">
                      Rank {lvl.rank}
                    </TableCell>
                    <TableCell>
                      <LevelBadge level={lvl.name} rank={lvl.rank} />
                    </TableCell>
                    <TableCell className="text-xs text-slate-600">
                      {lvl.description ||
                        (lvl.rank === 1
                          ? 'Public distribution permitted; minimal restrictions.'
                          : lvl.rank === 2
                          ? 'Default floor; company-internal circulation only.'
                          : lvl.rank === 3
                          ? 'Sensitive business, financial, or personal data; stream delivery.'
                          : 'Strictly restricted; critical PII or board materials; audited stream delivery.')}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Document Types Manager */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="md:col-span-2">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <FolderTree className="w-5 h-5 text-blue-600" />
                Hierarchical Document Types
              </CardTitle>
              <CardDescription>
                Classification types combined via confident first-match cascade.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {docTypesLoading ? (
                <TableSkeleton rows={5} cols={3} />
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Type Name</TableHead>
                      <TableHead>Slug</TableHead>
                      <TableHead className="text-right">Action</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {docTypes?.map((dt) => (
                      <TableRow key={dt.id}>
                        <TableCell className="font-semibold text-slate-900 text-xs">
                          {dt.name}
                        </TableCell>
                        <TableCell className="font-mono text-slate-500 text-xs">
                          {dt.slug}
                        </TableCell>
                        <TableCell className="text-right">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => deleteDocTypeMutation.mutate(dt.id)}
                            className="h-8 px-2 text-rose-600 hover:text-rose-700 hover:bg-rose-50"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Add Document Type */}
        <div>
          <Card>
            <CardHeader>
              <CardTitle className="text-sm">Create Document Type</CardTitle>
              <CardDescription className="text-xs">
                Add a new classification category.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <form onSubmit={handleCreateType} className="space-y-3 text-xs">
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">
                    Type Name
                  </label>
                  <Input
                    type="text"
                    placeholder="e.g. Invoices"
                    value={newTypeName}
                    onChange={(e) => {
                      setNewTypeName(e.target.value);
                      if (!newTypeSlug) {
                        setNewTypeSlug(
                          e.target.value.toLowerCase().replace(/[^a-z0-9]+/g, '-')
                        );
                      }
                    }}
                    required
                  />
                </div>

                <div>
                  <label className="block font-semibold text-slate-700 mb-1">
                    Slug
                  </label>
                  <Input
                    type="text"
                    placeholder="e.g. invoice"
                    value={newTypeSlug}
                    onChange={(e) => setNewTypeSlug(e.target.value)}
                    required
                  />
                </div>

                <div>
                  <label className="block font-semibold text-slate-700 mb-1">
                    Description
                  </label>
                  <Input
                    type="text"
                    placeholder="Optional description..."
                    value={newTypeDesc}
                    onChange={(e) => setNewTypeDesc(e.target.value)}
                  />
                </div>

                <Button
                  type="submit"
                  size="sm"
                  disabled={createDocTypeMutation.isPending || !newTypeName.trim()}
                  className="w-full mt-2"
                >
                  <Plus className="w-3.5 h-3.5 mr-1" />
                  {createDocTypeMutation.isPending ? 'Creating...' : 'Add Type'}
                </Button>
              </form>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
};
