import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';

/**
 * The departments the signed-in caller may assign a document to.
 *
 * The API returns only the caller's own visible subtree plus the mandatory
 * tenant root, so this list is already what the server will accept — the picker
 * cannot offer a choice that will be refused, and cannot show the rest of the
 * organisation's structure to someone who should not see it.
 */
export interface Department {
  id: string;
  name: string;
  parent_id: string | null;
  /** The tenant root. Required on every document, so the picker locks it on. */
  is_root: boolean;
  assignable: boolean;
}

export function useDepartments(enabled = true) {
  return useQuery({
    queryKey: ['departments'],
    queryFn: () => api.get<Department[]>('/v1/departments'),
    // The org chart does not change during a session.
    staleTime: 5 * 60 * 1000,
    enabled,
  });
}

/**
 * The root's id, or undefined until the list has loaded.
 *
 * Array-guarded rather than trusting the response shape: an error envelope or
 * a proxy returning an object here would otherwise throw inside a render and
 * take down the whole upload page, turning a missing list into a blank screen.
 */
export function rootDepartmentId(departments: Department[] | undefined): string | undefined {
  if (!Array.isArray(departments)) return undefined;
  return departments.find((d) => d.is_root)?.id;
}

/**
 * Add the root to a selection.
 *
 * The server adds it regardless, so a UI that let the user "save" without it
 * would show a selection that does not match what was stored.
 */
export function withRoot(selected: Set<string>, departments: Department[] | undefined): string[] {
  const root = rootDepartmentId(departments);
  const out = new Set(selected);
  if (root) out.add(root);
  return [...out];
}
