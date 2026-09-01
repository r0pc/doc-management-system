export enum Action {
  UPLOAD = 'upload',
  VIEW = 'view',
  DOWNLOAD = 'download',
  PREVIEW = 'preview',
  RECLASSIFY = 'reclassify',
  RESOLVE_REVIEW = 'resolve_review',
  MANAGE_TAXONOMY = 'manage_taxonomy',
  VIEW_AUDIT = 'view_audit',
  DELETE = 'delete',
}

export type Role = 'admin' | 'security_officer' | 'dept_manager' | 'employee' | 'viewer';

export const ROLE_PERMISSIONS: Record<Role, readonly Action[]> = {
  admin: [
    Action.UPLOAD,
    Action.VIEW,
    Action.DOWNLOAD,
    Action.PREVIEW,
    Action.RECLASSIFY,
    Action.RESOLVE_REVIEW,
    Action.MANAGE_TAXONOMY,
    Action.VIEW_AUDIT,
    Action.DELETE,
  ],
  security_officer: [
    Action.UPLOAD,
    Action.VIEW,
    Action.DOWNLOAD,
    Action.PREVIEW,
    Action.RECLASSIFY,
    Action.RESOLVE_REVIEW,
    Action.VIEW_AUDIT,
    Action.DELETE,
  ],
  dept_manager: [
    Action.UPLOAD,
    Action.VIEW,
    Action.DOWNLOAD,
    Action.PREVIEW,
    Action.RESOLVE_REVIEW,
  ],
  employee: [
    Action.UPLOAD,
    Action.VIEW,
    Action.DOWNLOAD,
    Action.PREVIEW,
  ],
  viewer: [
    Action.VIEW,
    Action.PREVIEW,
  ],
};
