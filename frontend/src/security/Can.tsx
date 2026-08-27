import React from 'react';
import { Action } from './permissions';
import { usePermissions } from './usePermissions';
import { DocumentSummary, DocumentView } from '../api/types';

export interface CanProps {
  action: Action;
  document?: DocumentSummary | DocumentView | null;
  fallback?: React.ReactNode;
  children: React.ReactNode;
}

/**
 * Cosmetic UI Gating Component (Invariant #33)
 * Renders children only if current user has permission for the specified Action.
 * Note: Server-side authorization remains the absolute security boundary.
 */
export const Can: React.FC<CanProps> = ({
  action,
  document,
  fallback = null,
  children,
}) => {
  const { can } = usePermissions();

  if (!can(action, document)) {
    return <>{fallback}</>;
  }

  return <>{children}</>;
};
