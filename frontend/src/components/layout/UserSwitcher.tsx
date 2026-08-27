import React from 'react';
import { useAuth, DEV_PERSONAS } from '../../api/auth';
import { UserCheck, Shield, ChevronDown } from 'lucide-react';

export const UserSwitcher: React.FC = () => {
  const { currentPersona, loginWithPersona } = useAuth();
  const [open, setOpen] = React.useState(false);

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2.5 px-3 py-1.5 rounded-lg bg-slate-100 hover:bg-slate-200/80 text-left transition-colors border border-slate-200 text-xs"
      >
        <div className="w-6 h-6 rounded-full bg-blue-600 text-white flex items-center justify-center font-bold text-xs">
          {currentPersona?.label[0] || 'U'}
        </div>
        <div className="hidden sm:block">
          <div className="font-semibold text-slate-800 flex items-center gap-1.5">
            {currentPersona?.label || 'Select Persona'}
            <span className="text-[10px] font-mono px-1 py-0.2 rounded bg-slate-200 text-slate-700">
              C{currentPersona?.clearance}
            </span>
          </div>
          <div className="text-[11px] text-slate-500">
            {currentPersona?.tenantLabel} · {currentPersona?.departmentLabel}
          </div>
        </div>
        <ChevronDown className="w-3.5 h-3.5 text-slate-400 ml-1" />
      </button>

      {open && (
        <>
          <div
            className="fixed inset-0 z-40"
            onClick={() => setOpen(false)}
            aria-hidden="true"
          />
          <div className="absolute right-0 mt-2 w-72 rounded-xl bg-white shadow-xl border border-slate-200 py-2 z-50 animate-in fade-in zoom-in-95 duration-150">
            <div className="px-3 py-1.5 text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
              Switch Persona (Dev Shim)
            </div>
            <div className="divide-y divide-slate-100">
              {DEV_PERSONAS.map((p) => {
                const isCurrent = currentPersona?.id === p.id;
                return (
                  <button
                    key={p.id}
                    type="button"
                    onClick={() => {
                      loginWithPersona(p);
                      setOpen(false);
                    }}
                    className={`w-full px-3 py-2.5 text-left flex items-start gap-2.5 hover:bg-slate-50 transition-colors ${
                      isCurrent ? 'bg-blue-50/60' : ''
                    }`}
                  >
                    <Shield
                      className={`w-4 h-4 mt-0.5 shrink-0 ${
                        p.clearance === 4
                          ? 'text-rose-600'
                          : p.clearance === 3
                          ? 'text-amber-600'
                          : 'text-blue-600'
                      }`}
                    />
                    <div className="flex-1 min-w-0 text-xs">
                      <div className="font-semibold text-slate-900 flex items-center justify-between">
                        <span>{p.label}</span>
                        {isCurrent && (
                          <UserCheck className="w-3.5 h-3.5 text-blue-600 shrink-0" />
                        )}
                      </div>
                      <div className="text-[11px] text-slate-500 mt-0.5">
                        <span className="font-medium text-slate-700 capitalize">
                          {p.role.replace('_', ' ')}
                        </span>{' '}
                        · Clearance {p.clearance}
                      </div>
                      <div className="text-[10px] text-slate-400 truncate">
                        {p.tenantLabel} · {p.departmentLabel}
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        </>
      )}
    </div>
  );
};
