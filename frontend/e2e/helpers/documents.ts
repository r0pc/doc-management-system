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

export async function softDelete(
  request: APIRequestContext,
  token: string,
  documentIds: string[]
): Promise<void> {
  // Teardown targets only ids this run created. There is no bulk delete route;
  // if none exists for single documents either, leave the rows and rely on the
  // RUN_ID prefix keeping them identifiable — never widen a DELETE to compensate.
  for (const id of documentIds) {
    await request
      .delete(`${API}/v1/documents/${id}`, { headers: { Authorization: `Bearer ${token}` } })
      .catch(() => undefined);
  }
}
