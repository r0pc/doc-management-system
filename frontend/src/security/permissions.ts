export enum Action {
  UPLOAD = 'upload',
  DOWNLOAD = 'download',
  PREVIEW = 'preview',
  RECLASSIFY = 'reclassify',
  RESOLVE_REVIEW = 'resolve_review',
  SEARCH = 'search',
  VIEW_AUDIT = 'view_audit',
  MANAGE_TAXONOMY = 'manage_taxonomy',
  MANAGE_USERS = 'manage_users',
}

export type Role = 'admin' | 'compliance_officer' | 'employee' | 'auditor';

export const ROLE_PERMISSIONS: Record<Role, readonly Action[]> = {
  admin: [
    Action.UPLOAD,
    Action.DOWNLOAD,
    Action.PREVIEW,
    Action.RECLASSIFY,
    Action.RESOLVE_REVIEW,
    Action.SEARCH,
    Action.VIEW_AUDIT,
    Action.MANAGE_TAXONOMY,
    Action.MANAGE_USERS,
  ],
  compliance_officer: [
    Action.UPLOAD,
    Action.DOWNLOAD,
    Action.PREVIEW,
    Action.RECLASSIFY,
    Action.RESOLVE_REVIEW,
    Action.SEARCH,
    Action.VIEW_AUDIT,
  ],
  employee: [
    Action.UPLOAD,
    Action.DOWNLOAD,
    Action.PREVIEW,
    Action.SEARCH,
  ],
  auditor: [
    Action.PREVIEW,
    Action.SEARCH,
    Action.VIEW_AUDIT,
  ],
};
