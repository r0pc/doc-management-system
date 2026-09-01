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
import { DetectorRules } from './DetectorRules';
import { PrototypeTrainer } from './PrototypeTrainer';
import { Shield, FolderTree, Plus, Trash2, ShieldAlert, Cpu } from 'lucide-react';

type AdminTab = 'taxonomy' | 'detectors' | 'prototypes';

export const TaxonomyPage: React.FC = () => {
  const queryClient = useQueryClient();

  const [activeTab, setActiveTab] = useState<AdminTab>('taxonomy');
  const [newTypeName, setNewTypeName] = useState('');
  const [newTypeParentId, setNewTypeParentId] = useState<string>('');
  const [newTypeDesc, setNewTypeDesc] = useState('');
  const [mutationError, setMutationError] = useState<unknown>(null);

  const {
    data: levels,
    isLoading: levelsLoading,
    error: levelsError,
  } = useQuery({
    queryKey: ['security-levels'],
    queryFn: () => api.get<SecurityLevelOut[]>('/v1/admin/security-levels'),
  });

  const {
    data: docTypes,
    isLoading: docTypesLoading,
    error: docTypesError,
  } = useQuery({
    queryKey: ['doc-types'],
    queryFn: () => api.get<DocTypeOut[]>('/v1/admin/doc-types'),
  });

  const createDocTypeMutation = useMutation({
    mutationFn: () =>
      api.post('/v1/admin/doc-types', {
        name: newTypeName.trim(),
        parent_id: newTypeParentId ? newTypeParentId : undefined,
        description: newTypeDesc || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['doc-types'] });
      setNewTypeName('');
      setNewTypeParentId('');
      setNewTypeDesc('');
      setMutationError(null);
    },
    onError: (err) => setMutationError(err),
  });

  const deleteDocTypeMutation = useMutation({
    mutationFn: (id: string) => api.delete(`/v1/admin/doc-types/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['doc-types'] });
      setMutationError(null);
    },
    onError: (err) => setMutationError(err),
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
          Taxonomy & Extensibility Administration
        </h2>
        <p className="text-xs text-[#656d76] dark:text-[#848d97] mt-0.5">
          Manage Security Levels, Document Types, Custom PII Detector Rules (#10), and Few-Shot Prototype Classifiers.
        </p>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-[#d0d7de] dark:border-[#30363d] space-x-2">
        <button
          type="button"
          onClick={() => setActiveTab('taxonomy')}
          className={`flex items-center gap-2 px-3 py-2 text-xs font-semibold border-b-2 transition-colors ${
            activeTab === 'taxonomy'
              ? 'border-[#0969da] text-[#0969da] dark:border-[#2f81f7] dark:text-[#2f81f7]'
              : 'border-transparent text-[#656d76] dark:text-[#848d97] hover:text-[#1f2328] dark:hover:text-[#e6edf3]'
          }`}
        >
          <FolderTree className="w-3.5 h-3.5" />
          Taxonomy & Levels
        </button>
        <button
          type="button"
          onClick={() => setActiveTab('detectors')}
          className={`flex items-center gap-2 px-3 py-2 text-xs font-semibold border-b-2 transition-colors ${
            activeTab === 'detectors'
              ? 'border-[#0969da] text-[#0969da] dark:border-[#2f81f7] dark:text-[#2f81f7]'
              : 'border-transparent text-[#656d76] dark:text-[#848d97] hover:text-[#1f2328] dark:hover:text-[#e6edf3]'
          }`}
        >
          <ShieldAlert className="w-3.5 h-3.5" />
          Detector Rules
        </button>
        <button
          type="button"
          onClick={() => setActiveTab('prototypes')}
          className={`flex items-center gap-2 px-3 py-2 text-xs font-semibold border-b-2 transition-colors ${
            activeTab === 'prototypes'
              ? 'border-[#0969da] text-[#0969da] dark:border-[#2f81f7] dark:text-[#2f81f7]'
              : 'border-transparent text-[#656d76] dark:text-[#848d97] hover:text-[#1f2328] dark:hover:text-[#e6edf3]'
          }`}
        >
          <Cpu className="w-3.5 h-3.5" />
          Prototype Classifier
        </button>
      </div>

      {activeTab === 'detectors' && <DetectorRules />}

      {activeTab === 'prototypes' && <PrototypeTrainer />}

      {activeTab === 'taxonomy' && (
        <div className="space-y-6">
          <ProblemAlert error={mutationError} />
          <ProblemAlert error={levelsError} />
          <ProblemAlert error={docTypesError} />

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
              ) : levelsError ? null : (
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
                    aria-label="Document type name"
                    placeholder="Type Name (e.g. Vendor MSA)"
                    value={newTypeName}
                    onChange={(e) => setNewTypeName(e.target.value)}
                    required
                  />
                  <select
                    aria-label="Parent document type"
                    value={newTypeParentId}
                    onChange={(e) => setNewTypeParentId(e.target.value)}
                    className="w-full h-9 rounded-md border border-[#d0d7de] dark:border-[#30363d] bg-white dark:bg-[#0d1117] px-3 py-1 text-xs text-[#1f2328] dark:text-[#e6edf3]"
                  >
                    <option value="">-- No Parent (Root Type) --</option>
                    {docTypes?.map((dt) => (
                      <option key={dt.id} value={dt.id}>
                        Parent: {dt.name}
                      </option>
                    ))}
                  </select>
                  <Input
                    type="text"
                    aria-label="Document type description"
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
              ) : docTypesError ? null : (
                <div className="bg-white dark:bg-[#0d1117] rounded-md border border-[#d0d7de] dark:border-[#30363d] overflow-hidden">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Type Name</TableHead>
                        <TableHead>Parent</TableHead>
                        <TableHead>Description</TableHead>
                        <TableHead className="text-right">Actions</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {docTypes && docTypes.length > 0 ? (
                        docTypes.map((dt) => {
                          const parent = docTypes.find((p) => p.id === dt.parent_id);
                          return (
                            <TableRow key={dt.id}>
                              <TableCell className="font-semibold text-xs text-[#1f2328] dark:text-[#e6edf3]">
                                {dt.name}
                              </TableCell>
                              <TableCell className="text-xs font-mono text-[#656d76] dark:text-[#848d97]">
                                {parent ? parent.name : '—'}
                              </TableCell>
                              <TableCell className="text-xs text-[#656d76] dark:text-[#848d97]">
                                {dt.description || '—'}
                              </TableCell>
                              <TableCell className="text-right">
                                <Button
                                  variant="destructive"
                                  size="sm"
                                  aria-label={`Delete document type ${dt.name}`}
                                  onClick={() => deleteDocTypeMutation.mutate(dt.id)}
                                  disabled={deleteDocTypeMutation.isPending}
                                  className="h-6 px-2 text-[10px]"
                                >
                                  <Trash2 className="w-3 h-3 mr-1" />
                                  Delete
                                </Button>
                              </TableCell>
                            </TableRow>
                          );
                        })
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
      )}
    </div>
  );
};
