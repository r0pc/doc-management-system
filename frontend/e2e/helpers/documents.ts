import type { APIRequestContext } from '@playwright/test';
import { API } from './api';
import * as fs from 'node:fs';

export async function uploadDocument(
  request: APIRequestContext,
  token: string,
  filePath: string,
  filename: string,
  contentType = 'application/pdf'
): Promise<string> {
  const bytes = fs.readFileSync(filePath);
  const auth = { Authorization: `Bearer ${token}` };

  const intent = await request.post(`${API}/v1/uploads`, {
    headers: auth,
    data: { filename, size_bytes: bytes.length, content_type: contentType },
  });
  if (!intent.ok()) throw new Error(`intent failed: ${intent.status()} ${await intent.text()}`);
  const { upload_id, presigned_put } = await intent.json();

  // Both transports are live: presigned POST for S3/MinIO (fields present),
  // plain PUT for the local dev backend (fields absent). Honour whichever the
  // server signed rather than assuming one.
  const fields: Record<string, string> = presigned_put.fields ?? {};
  if (Object.keys(fields).length > 0) {
    await request.post(presigned_put.url, {
      multipart: { ...fields, file: { name: filename, mimeType: contentType, buffer: bytes } },
    });
  } else {
    await request.put(presigned_put.url, {
      headers: { 'Content-Type': contentType },
      data: bytes,
    });
  }

  const done = await request.post(`${API}/v1/uploads/${upload_id}/complete`, {
    headers: auth,
    data: { size_bytes: bytes.length },
  });
  if (!done.ok()) throw new Error(`complete failed: ${done.status()} ${await done.text()}`);
  return upload_id;
}

/**
 * Documents this suite creates are NOT removed, and that is deliberate.
 *
 * The API exposes no DELETE for documents — deliberately, since `classifications`
 * is append-only and `access_log` holds no delete grant (#24). An earlier version
 * of this helper issued `DELETE /v1/documents/{id}` and swallowed the resulting
 * 405, which read as cleanup while doing nothing at all. Cleanup that silently
 * no-ops is worse than none: it hides the growth it claims to prevent.
 *
 * So rows accumulate under the `E2E-` prefix. Two consequences the suite must
 * respect, and does:
 *   - never assert on a total row count (another run may be mid-flight)
 *   - always PAGE a baseline rather than taking a single capped read, because
 *     MAX_PAGE_SIZE silently truncates once the corpus outgrows one page
 *
 * To reclaim a dev database, soft-delete by prefix — scoped, never unqualified:
 *   docker exec doc-management-system-postgres-1 psql -U docmgmt -d docmgmt \
 *     -c "UPDATE documents SET deleted_at=now()
 *         WHERE original_filename LIKE 'E2E-%' AND deleted_at IS NULL;"
 * That is `npm run test:e2e:clean`.
 */
export const E2E_PREFIX = 'E2E-';
