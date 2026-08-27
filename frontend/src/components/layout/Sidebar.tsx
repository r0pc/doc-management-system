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
    <aside className="w-60 border-r border-[#d0d7de] dark:border-[#30363d] bg-[#f6f8fa] dark:bg-[#0d1117] flex flex-col justify-between shrink-0 min-h-[calc(100vh-3.5rem)] p-3 transition-colors">
      <nav className="space-y-1">
        <div className="px-2 py-1.5 text-[11px] font-semibold uppercase tracking-wider text-[#656d76] dark:text-[#848d97]">
          Repositories
        </div>
        {navItems.map((item) => {
          const isSelected = currentTab === item.id;
          const buttonContent = (
            <button
              key={item.id}
              type="button"
              onClick={() => onSelectTab(item.id)}
              className={`w-full flex items-center justify-between px-2.5 py-1.5 rounded-md text-xs font-medium transition-colors ${
                isSelected
                  ? 'bg-[#0969da] text-white font-semibold shadow-xs dark:bg-[#1f6feb]'
                  : 'text-[#1f2328] dark:text-[#e6edf3] hover:bg-[#eaeef2] dark:hover:bg-[#21262d]'
              }`}
            >
              <div className="flex items-center gap-2.5">
                <span className={isSelected ? 'text-white' : 'text-[#656d76] dark:text-[#848d97]'}>
                  {item.icon}
                </span>
                <span>{item.label}</span>
              </div>
              {item.badge !== undefined && item.badge > 0 && (
                <span
                  className={`text-[10px] font-bold px-1.5 py-0.2 rounded-full ${
                    isSelected
                      ? 'bg-white text-[#0969da]'
                      : 'bg-[#fff8c5] dark:bg-[#9e6a03]/40 text-[#9a6700] dark:text-[#f2cc60] border border-[#d4a72c]/40'
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

      <div className="p-3 bg-white dark:bg-[#161b22] rounded-md border border-[#d0d7de] dark:border-[#30363d] text-[11px] text-[#656d76] dark:text-[#848d97] space-y-1">
        <div className="flex items-center gap-1.5 font-semibold text-[#1f2328] dark:text-[#e6edf3]">
          <Shield className="w-3.5 h-3.5 text-[#0969da] dark:text-[#2f81f7]" />
          <span>Security Model</span>
        </div>
        <p className="text-[10px] leading-relaxed text-[#656d76] dark:text-[#848d97]">
          Two-axis enforcement: Clearance Rank × Department Subtree.
        </p>
      </div>
    </aside>
  );
};
