export type SecurityLevelName = 'Public' | 'Internal' | 'Confidential' | 'Restricted';

export type DocumentStatus = 'quarantined' | 'processing' | 'ready' | 'failed' | 'held';

export interface PresignedPut {
  url: string;
  fields: Record<string, string>;
  expires_at: string;
}

export interface UploadIntentResponse {
  upload_id: string;
  presigned_put: PresignedPut;
}

export interface BatchFileRequest {
  filename: string;
  size_bytes: number;
  content_type: string;
}

export interface BatchUploadRequest {
  files: BatchFileRequest[];
}

export interface BatchUploadResponse {
  batch_id: string;
  uploads: UploadIntentResponse[];
}

export interface CompleteResponse {
  document_id: string;
  version_id: string;
  status: string;
  duplicate_of?: string | null;
}

export interface DocumentListItem {
  id: string;
  filename: string;
  status: DocumentStatus;
  level: string | null;
  doc_type: string | null;
  created_at: string;
  duplicate_of?: string[];
  level_rank?: number | null;
  /** Departments the document belongs to; empty means tenant-wide. */
  department_ids?: string[];
}

export interface DocumentPage {
  items: DocumentListItem[];
  next_cursor: string | null;
}

export interface RenameDocumentRequest {
  filename: string;
}

export interface BulkRenameItem {
  document_id: string;
  new_filename: string;
}

export interface BulkRenameRequest {
  items: BulkRenameItem[];
}

export interface BulkRenameResponse {
  renamed: string[];
}

export interface FindingOut {
  entity_type: string;
  rule_id: string;
  page_no: number | null;
  char_start: number;
  char_end: number;
  score: number;
  line_no?: number | null;
  snippet?: string | null;
  contributed_level?: string | null;
}

export interface PageTextOut {
  page_no: number;
  text: string;
}

export interface ClassificationJustification {
  level: string;
  level_rank: number;
  level_reason: string;
  doc_type: string | null;
  decided_by: string;
  confidence: number | null;
  confidence_threshold: number;
  keywords: string[];
  findings: FindingOut[];
}

export interface DocumentPreviewOut {
  id: string;
  filename: string;
  mime: string | null;
  char_count: number;
  pages: PageTextOut[];
  full_text: string;
  justification: ClassificationJustification;
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

export interface TrainPrototypeRequest {
  document_ids: string[];
}

export interface TrainPrototypeResponse {
  doc_type_id: string;
  sample_count: number;
  dimension: number;
}

export interface DocTypePrototypeOut {
  id: string;
  doc_type_id: string;
  sample_count: number;
  updated_at: string;
}

export interface DetectorRuleOut {
  id: string;
  entity_type: string;
  pattern: string;
  validator_kind: string;
  validator_config: Record<string, any>;
  context_words: string[];
  level_rank: number;
  enabled: boolean;
}

export interface DetectorRuleCreate {
  entity_type: string;
  pattern: string;
  validator_kind: string;
  validator_config: Record<string, any>;
  context_words: string[];
  level_rank: number;
  enabled?: boolean;
}

export interface DetectorRuleUpdate {
  pattern?: string;
  validator_kind?: string;
  validator_config?: Record<string, any>;
  context_words?: string[];
  level_rank?: number;
  enabled?: boolean;
}

export interface DetectorMatchOut {
  char_start: number;
  char_end: number;
  score: number;
}

export interface DetectorPreviewResponse {
  matches: DetectorMatchOut[];
}

export interface DepartmentOut {
  id: string;
  name: string;
  parent_id: string | null;
  is_root: boolean;
  assignable: boolean;
}

export interface DepartmentCreate {
  name: string;
  parent_id?: string | null;
}

export interface StatusBreakdown {
  ready: number;
  processing: number;
  quarantined: number;
  failed: number;
  held: number;
}

export interface LevelStat {
  name: string;
  rank: number;
  count: number;
  percentage: number;
}

export interface DocTypeStat {
  name: string;
  count: number;
  percentage: number;
}

export interface DepartmentStat {
  id: string;
  name: string;
  count: number;
}

export interface DecisionSourceStat {
  source: string;
  count: number;
}

export interface DailyIngestionStat {
  date: string;
  count: number;
}

export interface RecentDocumentStat {
  id: string;
  filename: string;
  status: DocumentStatus;
  level: string | null;
  doc_type: string | null;
  created_at: string;
}

export interface DocumentStatsOut {
  total_documents: number;
  total_storage_bytes: number;
  status_breakdown: StatusBreakdown;
  levels_breakdown: LevelStat[];
  doc_types_breakdown: DocTypeStat[];
  departments_breakdown: DepartmentStat[];
  decision_sources: DecisionSourceStat[];
  daily_ingestion: DailyIngestionStat[];
  recent_documents: RecentDocumentStat[];
  avg_confidence: number | null;
  pending_reviews_count: number;
}

