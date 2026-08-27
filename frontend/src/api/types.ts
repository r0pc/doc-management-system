export type SecurityLevelName = 'public' | 'internal' | 'confidential' | 'restricted';

export interface SecurityLevelOut {
  id: string;
  name: SecurityLevelName;
  rank: number;
  description?: string | null;
}

export interface DocTypeOut {
  id: string;
  name: string;
  slug: string;
  parent_id?: string | null;
  description?: string | null;
}

export type DocumentStatus = 'quarantined' | 'processing' | 'ready' | 'failed';

export interface DocumentSummary {
  id: string;
  tenant_id: string;
  department_id: string;
  title: string;
  current_version_id?: string | null;
  created_at: string;
  status: DocumentStatus;
  security_level_name?: SecurityLevelName | null;
  security_level_rank?: number | null;
  doc_type_name?: string | null;
  mime_type?: string | null;
  byte_size?: number | null;
}

export interface DocumentView extends DocumentSummary {
  sha256?: string | null;
  created_by?: string | null;
  updated_at?: string | null;
}

export interface FindingOut {
  id: string;
  entity_type: string;
  char_start: number;
  char_end: number;
  page_no: number;
  score: number;
}

export interface JobOut {
  id: string;
  stage: string;
  status: 'pending' | 'running' | 'succeeded' | 'failed';
  started_at?: string | null;
  completed_at?: string | null;
  error_message?: string | null;
}

export interface ReviewQueueItem {
  id: string;
  document_id: string;
  title: string;
  suggested_level_name?: SecurityLevelName | null;
  suggested_doc_type_name?: string | null;
  rule_confidence?: number | null;
  ml_confidence?: number | null;
  reasons: string[];
  created_at: string;
  status: 'pending' | 'resolved' | 'dismissed';
}

export interface AccessLogOut {
  id: string;
  created_at: string;
  action: string;
  actor_id?: string | null;
  document_id?: string | null;
  ip_address?: string | null;
  details?: Record<string, any> | null;
}

export interface SearchResultItem {
  id: string;
  title: string;
  security_level_name: SecurityLevelName;
  security_level_rank: number;
  doc_type_name?: string | null;
  snippet?: string | null;
  score: number;
}

export interface SearchResponse {
  query: string;
  results: SearchResultItem[];
  total: number;
  facets: {
    security_levels: Record<string, number>;
    doc_types: Record<string, number>;
  };
}

export interface ProblemDetails {
  type: string;
  title: string;
  status: number;
  detail?: string;
  instance?: string;
}

export interface UploadIntentResponse {
  upload_id: string;
  document_id: string;
  presigned_url: string;
  expires_in_seconds: number;
}

export interface CursorPaginated<T> {
  items: T[];
  next_cursor?: string | null;
  has_more: boolean;
}
