import { useAuth } from '../api/auth';
import { Action, ROLE_PERMISSIONS, Role } from './permissions';
import { DocumentSummary, DocumentView } from '../api/types';

export function usePermissions() {
  const { user } = useAuth();

  const can = (action: Action, document?: DocumentSummary | DocumentView | null): boolean => {
    if (!user) return false;

    // 1. Role action authorization
    const roleActions = ROLE_PERMISSIONS[user.role as Role] || [];
    if (!roleActions.includes(action)) {
      return false;
    }

    // 2. Document clearance checks if a document is provided
    if (document) {
      // If document is from another tenant, fail closed
      if (document.tenant_id && document.tenant_id !== user.tenant_id) {
        return false;
      }

      // Check clearance rank vs document security level rank
      const docRank = document.security_level_rank ?? 2; // default Internal rank 2
      if (user.clearance_rank < docRank) {
        return false;
      }
    }

    return true;
  };

  return {
    can,
    role: user?.role,
    clearanceRank: user?.clearance_rank ?? 1,
    tenantId: user?.tenant_id,
  };
}
