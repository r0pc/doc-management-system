import React from 'react';
import { UserSwitcher } from './UserSwitcher';
import { Shield, Sparkles } from 'lucide-react';

export const Navbar: React.FC = () => {
  return (
    <header className="h-16 border-b border-slate-200 bg-white px-6 flex items-center justify-between sticky top-0 z-30 shadow-xs">
      <div className="flex items-center gap-3">
        <div className="p-2 rounded-xl bg-blue-600 text-white shadow-sm flex items-center justify-center">
          <Shield className="w-5 h-5" />
        </div>
        <div>
          <h1 className="font-bold text-slate-900 text-base leading-tight tracking-tight flex items-center gap-2">
            Secure DMS
            <span className="text-[10px] uppercase font-bold tracking-wider px-1.5 py-0.5 rounded-full bg-blue-100 text-blue-800">
              v1.0
            </span>
          </h1>
          <p className="text-xs text-slate-500 hidden sm:block">
            Self-Hosted Classification & Multi-Tenant Access Control
          </p>
        </div>
      </div>

      <div className="flex items-center gap-4">
        <div className="hidden md:flex items-center gap-1.5 text-xs text-emerald-700 bg-emerald-50 px-2.5 py-1 rounded-full border border-emerald-200 font-medium">
          <Sparkles className="w-3.5 h-3.5" />
          <span>Airgapped & Self-Hosted</span>
        </div>
        <UserSwitcher />
      </div>
    </header>
  );
};
