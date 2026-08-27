import { useAuth } from '../api/auth';
import { Action, ROLE_PERMISSIONS, Role } from './permissions';
import { DocumentListItem } from '../api/types';

export function usePermissions() {
  const { user } = useAuth();

  const can = (action: Action, document?: DocumentListItem | null): boolean => {
    if (!user) return false;

    // 1. Role action authorization
    const roleActions = ROLE_PERMISSIONS[user.role as Role] || [];
    if (!roleActions.includes(action)) {
      return false;
    }

    // 2. Document clearance checks if a document is provided
    if (document) {
      // Check clearance rank vs document security level rank
      const rankMap: Record<string, number> = {
        'public': 1,
        'internal': 2,
        'confidential': 3,
        'restricted': 4,
      };
      const docRank = document.level ? (rankMap[document.level.toLowerCase()] ?? 2) : 2;
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
