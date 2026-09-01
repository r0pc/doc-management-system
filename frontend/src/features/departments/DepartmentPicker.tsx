import React from 'react';
import { Building2, Lock } from 'lucide-react';
import { Department, useDepartments } from './useDepartments';

/**
 * Checkbox list of departments, with the tenant root locked on.
 *
 * The root is shown checked and disabled rather than hidden: a document always
 * belongs to it, and hiding that would make the stored set differ from what the
 * user was shown. The lock is cosmetic like every client-side rule here (#33) —
 * the API adds the root and refuses a set without it regardless.
 */
export const DepartmentPicker: React.FC<{
  selected: Set<string>;
  onChange: (next: Set<string>) => void;
  disabled?: boolean;
}> = ({ selected, onChange, disabled }) => {
  const { data: departments, isLoading, isError } = useDepartments();

  const toggle = (dept: Department) => {
    if (dept.is_root) return;
    const next = new Set(selected);
    if (next.has(dept.id)) next.delete(dept.id);
    else next.add(dept.id);
    onChange(next);
  };

  if (isLoading) {
    return (
      <p className="text-[11px] text-[#656d76] dark:text-[#848d97]">Loading departments…</p>
    );
  }
  if (isError || !Array.isArray(departments) || departments.length === 0) {
    return (
      // `status`, not `alert`: a secondary list failing to load is not an
      // assertive interruption, and using `alert` here competes with the
      // form's real error region for the same announcement.
      <p className="text-[11px] text-[#cf222e] dark:text-[#f85149]" role="status">
        Could not load departments.
      </p>
    );
  }

  return (
    <ul className="space-y-1" data-testid="department-picker">
      {departments.map((dept) => {
        const checked = dept.is_root || selected.has(dept.id);
        return (
          <li key={dept.id}>
            <label
              className={`flex items-center gap-2 text-xs ${
                dept.is_root || disabled ? 'opacity-70' : 'cursor-pointer'
              }`}
            >
              <input
                type="checkbox"
                data-testid="department-option"
                data-department={dept.name}
                checked={checked}
                disabled={dept.is_root || disabled}
                onChange={() => toggle(dept)}
                className="rounded border-[#d0d7de] dark:border-[#30363d]"
              />
              <Building2 className="w-3.5 h-3.5 text-[#656d76] dark:text-[#848d97] shrink-0" />
              <span className="text-[#1f2328] dark:text-[#e6edf3]">{dept.name}</span>
              {dept.is_root && (
                <span className="inline-flex items-center gap-1 text-[10px] text-[#656d76] dark:text-[#848d97]">
                  <Lock className="w-3 h-3" /> always included
                </span>
              )}
            </label>
          </li>
        );
      })}
    </ul>
  );
};
