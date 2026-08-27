export type SecurityLevelName = 'Public' | 'Internal' | 'Confidential' | 'Restricted';

export type DocumentStatus = 'quarantined' | 'processing' | 'ready' | 'failed' | 'held';

export interface PresignedPut {
  url: string;
  expires_at: string;
}

export interface UploadIntentResponse {
  upload_id: string;
  presigned_put: PresignedPut;
}

export interface CompleteResponse {
  document_id: string;
  version_id: string;
  status: string;
}

export interface DocumentListItem {
  id: string;
  filename: string;
  status: DocumentStatus;
  level: string | null;
  doc_type: string | null;
  created_at: string;
}

export interface DocumentPage {
  items: DocumentListItem[];
  next_cursor: string | null;
}

export interface FindingOut {
  entity_type: string;
  rule_id: string;
  page_no: number | null;
  char_start: number;
  char_end: number;
  score: number;
}

export interface JobOut {
  stage: string;
  state: string;
  attempts: number;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface ReviewQueueItem {
  review_id: string;
  document_id: string;
  filename: string;
  level: string | null;
  doc_type: string | null;
  confidence: number | null;
  decided_by: string | null;
  findings_count: number | null;
  created_at: string;
}

export interface ReviewPage {
  items: ReviewQueueItem[];
  next_cursor: string | null;
}

export interface ReclassifyRequest {
  level_name: SecurityLevelName;
  doc_type_id: string | null;
}

export interface ResolveReviewRequest {
  level_name: SecurityLevelName;
  doc_type_id: string | null;
  decision: 'accept' | 'correct';
}

export interface LabelView {
  document_id: string;
  level: string;
  doc_type_id: string | null;
  decided_by: string;
}

export interface AuditLogEntry {
  id: number;
  document_id: string | null;
  actor_id: string | null;
  action: string;
  ip: string | null;
  user_agent: string | null;
  ts: string;
}

export interface AuditPage {
  items: AuditLogEntry[];
  next_cursor: string | null;
}

export interface SearchHit {
  version_id: string;
  document_id: string;
  filename: string;
  level: string | null;
  doc_type: string | null;
  snippet: string;
  score: number;
}

export interface Facets {
  levels: Record<string, number>;
  doc_types: Record<string, number>;
}

export interface SearchResponse {
  results: SearchHit[];
  facets: Facets;
  total_candidates: number;
}

export interface ProblemDetails {
  type: string;
  title: string;
  status: number;
  detail: string;
  instance?: string;
  [key: string]: any;
}

export interface DocTypeOut {
  id: string;
  parent_id: string | null;
  name: string;
  description: string;
}

export interface SecurityLevelOut {
  id: string;
  rank: number;
  name: string;
  description: string;
}

export interface CursorPaginated<T> {
  items: T[];
  next_cursor: string | null;
}
