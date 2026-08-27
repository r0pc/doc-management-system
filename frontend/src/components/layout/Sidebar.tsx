import React from 'react';
import {
  FileText,
  UploadCloud,
  CheckSquare,
  Search,
  History,
  Settings,
  Shield,
} from 'lucide-react';
import { Action } from '../../security/permissions';
import { Can } from '../../security/Can';

export type NavTab = 'documents' | 'upload' | 'review' | 'search' | 'audit' | 'admin';

interface SidebarProps {
  currentTab: NavTab;
  onSelectTab: (tab: NavTab) => void;
  reviewCount?: number;
}

export const Sidebar: React.FC<SidebarProps> = ({
  currentTab,
  onSelectTab,
  reviewCount = 0,
}) => {
  const navItems: Array<{
    id: NavTab;
    label: string;
    icon: React.ReactNode;
    action?: Action;
    badge?: number;
  }> = [
    {
      id: 'documents',
      label: 'Documents',
      icon: <FileText className="w-4 h-4" />,
    },
    {
      id: 'upload',
      label: 'Upload New',
      icon: <UploadCloud className="w-4 h-4" />,
      action: Action.UPLOAD,
    },
    {
      id: 'review',
      label: 'Review Queue',
      icon: <CheckSquare className="w-4 h-4" />,
      action: Action.RESOLVE_REVIEW,
      badge: reviewCount,
    },
    {
      id: 'search',
      label: 'Hybrid Search',
      icon: <Search className="w-4 h-4" />,
      action: Action.SEARCH,
    },
    {
      id: 'audit',
      label: 'Audit Trail',
      icon: <History className="w-4 h-4" />,
      action: Action.VIEW_AUDIT,
    },
    {
      id: 'admin',
      label: 'Taxonomy Admin',
      icon: <Settings className="w-4 h-4" />,
      action: Action.MANAGE_TAXONOMY,
    },
  ];

  return (
    <aside className="w-64 border-r border-slate-200 bg-white flex flex-col justify-between shrink-0 min-h-[calc(100vh-4rem)] p-4">
      <nav className="space-y-1.5">
        <div className="px-3 py-2 text-[11px] font-bold uppercase tracking-wider text-slate-400">
          Navigation
        </div>
        {navItems.map((item) => {
          const isSelected = currentTab === item.id;
          const buttonContent = (
            <button
              key={item.id}
              type="button"
              onClick={() => onSelectTab(item.id)}
              className={`w-full flex items-center justify-between px-3 py-2.5 rounded-lg text-xs font-medium transition-all ${
                isSelected
                  ? 'bg-blue-600 text-white shadow-xs font-semibold'
                  : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900'
              }`}
            >
              <div className="flex items-center gap-3">
                <span className={isSelected ? 'text-white' : 'text-slate-400'}>
                  {item.icon}
                </span>
                <span>{item.label}</span>
              </div>
              {item.badge !== undefined && item.badge > 0 && (
                <span
                  className={`text-[10px] font-bold px-1.5 py-0.2 rounded-full ${
                    isSelected
                      ? 'bg-white text-blue-700'
                      : 'bg-amber-100 text-amber-800'
                  }`}
                >
                  {item.badge}
                </span>
              )}
            </button>
          );

          if (item.action) {
            return (
              <Can key={item.id} action={item.action}>
                {buttonContent}
              </Can>
            );
          }

          return buttonContent;
        })}
      </nav>

      <div className="p-3 bg-slate-50 rounded-xl border border-slate-200/80 text-[11px] text-slate-500 space-y-1">
        <div className="flex items-center gap-1.5 font-semibold text-slate-700">
          <Shield className="w-3.5 h-3.5 text-blue-600" />
          <span>Security Model</span>
        </div>
        <p className="text-[10px] leading-relaxed text-slate-500">
          Two-axis enforcement: Clearance Rank × Department Subtree.
        </p>
      </div>
    </aside>
  );
};
