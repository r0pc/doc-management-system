import React from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Building2, Pencil } from 'lucide-react';
import { api } from '../../api/client';
import { DocumentListItem } from '../../api/types';
import { Button } from '../../components/ui/button';
import { ProblemAlert } from '../../components/common/ProblemAlert';
import { Action } from '../../security/permissions';
import { usePermissions } from '../../security/usePermissions';
import { DepartmentPicker } from './DepartmentPicker';
import { useDepartments, withRoot } from './useDepartments';

/**
 * A document's departments, with in-place editing for those who may change it.
 *
 * This is the second axis of #25 made visible. A reader who cannot see why a
 * colleague's document is invisible to them has no way to tell an access rule
 * from a fault — which is exactly how "no documents found" got reported as a
 * bug when it was the department filter doing its job.
 *
 * The Edit control is cosmetic gating (#33): the API refuses a caller without
 * MANAGE_DEPARTMENTS regardless, and re-checks the root rule and assignability
 * on every write.
 */
export const DocumentDepartments: React.FC<{ doc: DocumentListItem }> = ({ doc }) => {
  const { can } = usePermissions();
  const mayEdit = can(Action.MANAGE_DEPARTMENTS);
  const queryClient = useQueryClient();

  const { data: departments } = useDepartments();
  const [editing, setEditing] = React.useState(false);
  const [selected, setSelected] = React.useState<Set<string>>(new Set());
  const [error, setError] = React.useState<unknown>(null);

  const current = React.useMemo(() => new Set(doc.department_ids ?? []), [doc.department_ids]);
  const nameOf = (id: string) =>
    (Array.isArray(departments) ? departments : []).find((d) => d.id === id)?.name ?? 'Unknown';

  const save = useMutation({
    mutationFn: () =>
      api.post('/v1/documents/departments', {
        document_ids: [doc.id],
        department_ids: withRoot(selected, departments),
      }),
    onSuccess: () => {
      setEditing(false);
      queryClient.invalidateQueries({ queryKey: ['document', doc.id] });
      queryClient.invalidateQueries({ queryKey: ['documents'] });
    },
    onError: (err: unknown) => setError(err),
  });

  const startEditing = () => {
    // Seed from what the document actually has, so Save without changes is a
    // no-op rather than a silent narrowing to nothing.
    setSelected(new Set(current));
    setError(null);
    setEditing(true);
  };

  return (
    <div className="space-y-2" data-testid="document-departments">
      <div className="flex items-center justify-between">
        <h4 className="font-semibold text-xs text-[#1f2328] dark:text-[#e6edf3] flex items-center gap-1.5">
          <Building2 className="w-3.5 h-3.5 text-[#656d76] dark:text-[#848d97]" />
          Departments
        </h4>
        {mayEdit && !editing && (
          <Button
            variant="outline"
            size="sm"
            data-testid="edit-departments"
            onClick={startEditing}
            className="h-6 px-2 text-[11px]"
          >
            <Pencil className="w-3 h-3 mr-1" /> Edit
          </Button>
        )}
      </div>

      {!editing && (
        <div className="flex flex-wrap gap-1.5">
          {current.size === 0 ? (
            <span className="text-[11px] text-[#656d76] dark:text-[#848d97]">
              Tenant-wide — visible to every department.
            </span>
          ) : (
            [...current].map((id) => (
              <span
                key={id}
                data-testid="document-department"
                className="px-2 py-0.5 rounded-full text-[11px] bg-[#f6f8fa] dark:bg-[#21262d] border border-[#d0d7de] dark:border-[#30363d] text-[#656d76] dark:text-[#848d97]"
              >
                {nameOf(id)}
              </span>
            ))
          )}
        </div>
      )}

      {editing && (
        <div className="rounded-md border border-[#d0d7de] dark:border-[#30363d] p-2.5 space-y-2">
          <DepartmentPicker
            selected={selected}
            onChange={setSelected}
            disabled={save.isPending}
          />
          {error != null && <ProblemAlert error={error} />}
          <div className="flex justify-end gap-2">
            <Button
              variant="outline"
              size="sm"
              data-testid="cancel-departments"
              onClick={() => setEditing(false)}
              className="h-6 px-2 text-[11px]"
            >
              Cancel
            </Button>
            <Button
              size="sm"
              data-testid="save-departments"
              disabled={save.isPending}
              onClick={() => {
                setError(null);
                save.mutate();
              }}
              className="h-6 px-2 text-[11px]"
            >
              {save.isPending ? 'Saving…' : 'Save'}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
};
