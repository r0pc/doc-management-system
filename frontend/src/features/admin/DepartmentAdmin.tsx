import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../../api/client';
import { DepartmentOut } from '../../api/types';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../../components/ui/card';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '../../components/ui/table';
import { TableSkeleton } from '../../components/common/LoadingSkeleton';
import { ProblemAlert } from '../../components/common/ProblemAlert';
import { Building2, Plus, Lock, CheckCircle, FolderTree } from 'lucide-react';

export const DepartmentAdmin: React.FC = () => {
  const queryClient = useQueryClient();
  const [name, setName] = useState('');
  const [parentId, setParentId] = useState<string>('');
  const [formError, setFormError] = useState<unknown>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const {
    data: departments,
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: ['departments'],
    queryFn: () => api.get<DepartmentOut[]>('/v1/departments'),
  });

  const createDepartmentMutation = useMutation({
    mutationFn: () =>
      api.post<DepartmentOut>('/v1/departments', {
        name: name.trim(),
        parent_id: parentId ? parentId : undefined,
      }),
    onSuccess: (newDept) => {
      queryClient.invalidateQueries({ queryKey: ['departments'] });
      queryClient.invalidateQueries({ queryKey: ['document-stats'] });
      setName('');
      setParentId('');
      setFormError(null);
      setSuccessMessage(`Department "${newDept.name}" created successfully.`);
      setTimeout(() => setSuccessMessage(null), 4000);
    },
    onError: (err) => {
      setFormError(err);
      setSuccessMessage(null);
    },
  });

  const handleCreate = (e: React.FormEvent) => {
    e.preventDefault();
    if (name.trim()) {
      createDepartmentMutation.mutate();
    }
  };

  const rootDept = departments?.find((d) => d.is_root);

  return (
    <div className="space-y-6" data-testid="department-admin">
      <ProblemAlert error={formError} />
      <ProblemAlert error={isError ? error : null} />

      {successMessage && (
        <div
          role="status"
          className="p-3 rounded-md bg-[#dafbe1] dark:bg-[#1f883d]/20 border border-[#4ac26b]/40 text-xs text-[#1a7f37] dark:text-[#3fb950] flex items-center gap-2"
        >
          <CheckCircle className="w-4 h-4 shrink-0" />
          <span>{successMessage}</span>
        </div>
      )}

      {/* 1. Create New Department Form */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Building2 className="w-4 h-4 text-[#0969da] dark:text-[#2f81f7]" />
            Add Organizational Department
          </CardTitle>
          <CardDescription>
            Create additional departmental subtrees for access partitioning and document assignment (Axis 2: Department Subtree).
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleCreate} className="p-4 bg-[#f6f8fa] dark:bg-[#161b22] border border-[#d0d7de] dark:border-[#30363d] rounded-md space-y-3">
            <div className="font-semibold text-xs text-[#1f2328] dark:text-[#e6edf3]">
              Department Details
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className="block text-[11px] font-medium text-[#656d76] dark:text-[#848d97] mb-1">
                  Department Name *
                </label>
                <Input
                  type="text"
                  aria-label="Department name"
                  placeholder="e.g. Legal, Finance, Marketing, Infrastructure"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  required
                />
              </div>

              <div>
                <label className="block text-[11px] font-medium text-[#656d76] dark:text-[#848d97] mb-1">
                  Parent Department
                </label>
                <select
                  aria-label="Parent department"
                  value={parentId}
                  onChange={(e) => setParentId(e.target.value)}
                  className="w-full h-9 rounded-md border border-[#d0d7de] dark:border-[#30363d] bg-white dark:bg-[#0d1117] px-3 py-1 text-xs text-[#1f2328] dark:text-[#e6edf3]"
                >
                  <option value="">
                    {rootDept ? `Default: Tenant Root (${rootDept.name})` : '-- Root Department --'}
                  </option>
                  {departments?.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.is_root ? `[Root] ${d.name}` : `Child of ${d.name}`}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className="flex justify-end pt-1">
              <Button
                type="submit"
                variant="default"
                size="sm"
                disabled={createDepartmentMutation.isPending || !name.trim()}
              >
                <Plus className="w-3.5 h-3.5 mr-1" />
                {createDepartmentMutation.isPending ? 'Creating...' : 'Create Department'}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      {/* 2. Existing Departments List Table */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FolderTree className="w-4 h-4 text-[#1a7f37] dark:text-[#3fb950]" />
            Configured Departments & Hierarchy
          </CardTitle>
          <CardDescription>
            All departments configured within this tenant. Documents assigned to a department are visible to its descendants.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <TableSkeleton rows={4} cols={4} />
          ) : isError ? null : (
            <div className="bg-white dark:bg-[#0d1117] rounded-md border border-[#d0d7de] dark:border-[#30363d] overflow-hidden">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Department Name</TableHead>
                    <TableHead>Parent Department</TableHead>
                    <TableHead>Type & Scope</TableHead>
                    <TableHead className="font-mono text-right">Identifier</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {departments && departments.length > 0 ? (
                    departments.map((dept) => {
                      const parent = departments.find((p) => p.id === dept.parent_id);
                      return (
                        <TableRow key={dept.id}>
                          <TableCell className="font-semibold text-xs text-[#1f2328] dark:text-[#e6edf3]">
                            <div className="flex items-center gap-2">
                              <Building2 className="w-3.5 h-3.5 text-[#656d76] dark:text-[#848d97]" />
                              <span>{dept.name}</span>
                            </div>
                          </TableCell>
                          <TableCell className="text-xs text-[#656d76] dark:text-[#848d97]">
                            {parent ? parent.name : dept.is_root ? '— (Top-Level Root)' : '—'}
                          </TableCell>
                          <TableCell className="text-xs">
                            {dept.is_root ? (
                              <span className="inline-flex items-center gap-1 text-[11px] font-bold px-2 py-0.5 rounded bg-[#ddf4ff] dark:bg-[#1f6feb]/20 text-[#0969da] dark:text-[#2f81f7] border border-[#54aeff]/40">
                                <Lock className="w-3 h-3" /> Tenant Root
                              </span>
                            ) : (
                              <span className="text-[11px] font-medium px-2 py-0.5 rounded bg-[#f6f8fa] dark:bg-[#21262d] text-[#656d76] dark:text-[#848d97] border border-[#d0d7de] dark:border-[#30363d]">
                                Sub-Department
                              </span>
                            )}
                          </TableCell>
                          <TableCell className="font-mono text-[10px] text-[#656d76] dark:text-[#848d97] text-right">
                            {dept.id}
                          </TableCell>
                        </TableRow>
                      );
                    })
                  ) : (
                    <TableRow>
                      <TableCell colSpan={4} className="text-center py-6 text-xs text-[#656d76] dark:text-[#848d97]">
                        No departments found.
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
