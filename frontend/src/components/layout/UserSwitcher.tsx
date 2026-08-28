import React from 'react';
import { useAuth, DEV_PERSONAS } from '../../api/auth';
import { UserCheck, Shield, ChevronDown } from 'lucide-react';

export const UserSwitcher: React.FC = () => {
  const { currentPersona, loginWithPersona, devPersonasEnabled } = useAuth();
  const [open, setOpen] = React.useState(false);
  const triggerRef = React.useRef<HTMLButtonElement>(null);
  const menuRef = React.useRef<HTMLDivElement>(null);

  // Escape closes the menu and returns focus to the trigger, so the control is
  // operable and escapable without a pointer.
  React.useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpen(false);
        triggerRef.current?.focus();
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [open]);

  React.useEffect(() => {
    if (!open) return;
    const first = menuRef.current?.querySelector<HTMLButtonElement>('button');
    first?.focus();
  }, [open]);

  // Belt and braces with Navbar's gate: this component must not render itself
  // if the shim is disabled, whatever mounts it.
  if (!devPersonasEnabled) return null;

  return (
    <div className="relative">
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen(!open)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={
          currentPersona
            ? `Switch dev persona. Current: ${currentPersona.label}, clearance ${currentPersona.clearance}`
            : 'Select a dev persona'
        }
        className="flex items-center gap-2 px-2.5 py-1 rounded-md bg-[#f6f8fa] dark:bg-[#21262d] hover:bg-[#eaeef2] dark:hover:bg-[#30363d] text-left transition-colors border border-[#d0d7de] dark:border-[#30363d] text-xs shadow-2xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0969da]"
      >
        <div className="w-5 h-5 rounded-full bg-[#0969da] dark:bg-[#2f81f7] text-white flex items-center justify-center font-bold text-[10px]">
          {currentPersona?.label[0] || 'U'}
        </div>
        <div className="hidden sm:block">
          <div className="font-semibold text-[#1f2328] dark:text-[#e6edf3] flex items-center gap-1.5 leading-tight">
            {currentPersona?.label.split(' ')[0] || 'Select'}
            <span className="text-[10px] font-mono px-1 py-0.1 rounded bg-[#eaeef2] dark:bg-[#30363d] text-[#656d76] dark:text-[#848d97]">
              C{currentPersona?.clearance}
            </span>
          </div>
        </div>
        <ChevronDown className="w-3.5 h-3.5 text-[#656d76] dark:text-[#848d97] ml-0.5" />
      </button>

      {open && (
        <>
          <div
            className="fixed inset-0 z-40"
            onClick={() => setOpen(false)}
            aria-hidden="true"
          />
          <div
            ref={menuRef}
            role="menu"
            aria-label="Dev personas"
            className="absolute right-0 mt-1.5 w-72 rounded-md bg-white dark:bg-[#161b22] shadow-xl border border-[#d0d7de] dark:border-[#30363d] py-1.5 z-50 animate-in fade-in duration-100"
          >
            <div className="px-3 py-1 text-[11px] font-semibold text-[#656d76] dark:text-[#848d97] uppercase tracking-wider border-b border-[#d0d7de] dark:border-[#30363d] pb-1.5 mb-1">
              Switch Persona (Dev Shim)
            </div>
            <div className="divide-y divide-[#d8dee4]/50 dark:divide-[#30363d]/50">
              {DEV_PERSONAS.map((p) => {
                const isCurrent = currentPersona?.id === p.id;
                return (
                  <button
                    key={p.id}
                    type="button"
                    role="menuitemradio"
                    aria-checked={isCurrent}
                    onClick={() => {
                      void loginWithPersona(p);
                      setOpen(false);
                      triggerRef.current?.focus();
                    }}
                    className={`w-full px-3 py-2 text-left flex items-start gap-2.5 hover:bg-[#f6f8fa] dark:hover:bg-[#21262d] transition-colors focus-visible:outline-none focus-visible:bg-[#eaeef2] dark:focus-visible:bg-[#30363d] ${
                      isCurrent ? 'bg-[#ddf4ff]/50 dark:bg-[#388bfd]/15' : ''
                    }`}
                  >
                    <Shield
                      className={`w-3.5 h-3.5 mt-0.5 shrink-0 ${
                        p.clearance === 4
                          ? 'text-[#cf222e] dark:text-[#f85149]'
                          : p.clearance === 3
                          ? 'text-[#9a6700] dark:text-[#d29922]'
                          : 'text-[#0969da] dark:text-[#2f81f7]'
                      }`}
                    />
                    <div className="flex-1 min-w-0 text-xs">
                      <div className="font-semibold text-[#1f2328] dark:text-[#e6edf3] flex items-center justify-between">
                        <span>{p.label}</span>
                        {isCurrent && (
                          <UserCheck className="w-3.5 h-3.5 text-[#0969da] dark:text-[#2f81f7] shrink-0" />
                        )}
                      </div>
                      <div className="text-[11px] text-[#656d76] dark:text-[#848d97] mt-0.5">
                        <span className="font-medium text-[#1f2328] dark:text-[#e6edf3] capitalize">
                          {p.role.replace('_', ' ')}
                        </span>{' '}
                        · Clearance {p.clearance}
                      </div>
                      <div className="text-[10px] text-[#656d76] dark:text-[#848d97] truncate">
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
