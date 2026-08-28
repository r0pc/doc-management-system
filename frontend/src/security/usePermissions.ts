import { useAuth } from '../api/auth';
import { Action, ROLE_PERMISSIONS, Role } from './permissions';
import { levelRank } from './levels';
import { DocumentListItem } from '../api/types';

/**
 * COSMETIC UI GATING ONLY (invariant #33).
 *
 * Everything below decides which controls are *drawn*. It is not, and must
 * never be treated as, an authorization decision:
 *
 *  - the claims it reads come from an unverified client-side JWT decode;
 *  - `document.level` is whatever the last list response happened to say, and
 *    can be stale or absent;
 *  - a user can flip any of it from the devtools console.
 *
 * The API re-authorizes every request against the verified token and the
 * `documents` row (invariant #15). Hiding a button here prevents confusion, not
 * access. Never use `can()` in place of a server check, and never let a `true`
 * from here be the only thing standing between a user and a byte of content.
 */
export function usePermissions() {
  const { user } = useAuth();

  const can = (action: Action, document?: DocumentListItem | null): boolean => {
    if (!user) return false;

    // 1. Role action authorization
    const roleActions = ROLE_PERMISSIONS[user.role as Role] || [];
    if (!roleActions.includes(action)) {
      return false;
    }

    // 2. Document clearance check when a document is supplied. Unknown or
    //    missing levels floor at Internal, never Public (invariant #9), so an
    //    unclassified document is never shown as more accessible than it is.
    if (document) {
      if (user.clearance_rank < levelRank(document.level)) {
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
