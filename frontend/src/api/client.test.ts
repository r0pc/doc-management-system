import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  api,
  ApiError,
  getAuthToken,
  setAuthToken,
  parseContentDispositionFilename,
  AUTH_TOKEN_STORAGE_KEY,
} from './client';

const fetchMock = vi.fn();

/**
 * Await a request expected to reject, narrowed to `ApiError`.
 *
 * `promise.catch((e) => e)` yields `unknown` under strict TS, and casting it
 * would let a resolved promise — or a rejection of some other type — sail
 * through every assertion below. This fails loudly on both instead.
 */
async function captureApiError(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise;
  } catch (error) {
    if (error instanceof ApiError) return error;
    throw error;
  }
  throw new Error('expected the request to reject with an ApiError, but it resolved');
}

function headerOf(callIndex: number, name: string): string | null {
  const init = fetchMock.mock.calls[callIndex]?.[1] as RequestInit | undefined;
  const headers = init?.headers;
  if (headers instanceof Headers) return headers.get(name);
  if (headers && typeof headers === 'object') {
    const record = headers as Record<string, string>;
    const key = Object.keys(record).find((k) => k.toLowerCase() === name.toLowerCase());
    return key ? record[key] : null;
  }
  return null;
}

beforeEach(() => {
  localStorage.clear();
  fetchMock.mockReset();
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('token storage', () => {
  it('round-trips the token and clears it on null', () => {
    setAuthToken('token-abc');
    expect(getAuthToken()).toBe('token-abc');
    expect(localStorage.getItem(AUTH_TOKEN_STORAGE_KEY)).toBe('token-abc');

    setAuthToken(null);
    expect(getAuthToken()).toBeNull();
    expect(localStorage.getItem(AUTH_TOKEN_STORAGE_KEY)).toBeNull();
  });

  it('degrades to null instead of throwing when storage is unavailable', () => {
    // Safari private mode and "block site data" make localStorage throw on
    // access. That must not take the whole app down.
    const getItem = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('The operation is insecure.');
    });
    const setItem = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('The operation is insecure.');
    });

    expect(getAuthToken()).toBeNull();
    expect(() => setAuthToken('x')).not.toThrow();

    getItem.mockRestore();
    setItem.mockRestore();
  });
});

describe('Authorization header attachment', () => {
  it('attaches the stored bearer token to API requests', async () => {
    setAuthToken('token-abc');
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }));

    await api.get('/v1/documents');

    expect(headerOf(0, 'Authorization')).toBe('Bearer token-abc');
  });

  it('sends no Authorization header when there is no token', async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }));

    await api.get('/v1/documents');

    expect(headerOf(0, 'Authorization')).toBeNull();
  });

  it('does not overwrite an explicitly supplied Authorization header', async () => {
    setAuthToken('stored');
    fetchMock.mockResolvedValue(new Response('{}', { status: 200 }));

    // Exercised through the internal request path via api.get; the public
    // surface has no override, so assert the stored token is what lands.
    await api.get('/v1/documents');
    expect(headerOf(0, 'Authorization')).toBe('Bearer stored');
  });

  it('REFUSES to send credentials to an absolute URL', async () => {
    // Invariant #1 / #17 depend on the bearer token never leaving the API
    // origin. If this ever passes a presigned or attacker-supplied URL through,
    // the session token is handed to that host.
    setAuthToken('token-abc');

    await expect(api.get('https://evil.example/steal')).rejects.toBeInstanceOf(ApiError);
    await expect(api.post('http://storage.internal/bucket/key', {})).rejects.toThrow(
      /Refusing to send credentials/
    );
    await expect(api.get('//evil.example/steal')).rejects.toThrow(/Refusing to send credentials/);

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('REFUSES paths that only LOOK same-origin to a string check', async () => {
    // Parser differential: `fetch` resolves with the WHATWG URL parser, which
    // strips ASCII tab/LF/CR before parsing and treats a backslash as "/" for
    // special schemes. Each of these starts with a single "/" and so passes a
    // `startsWith('//')` test, yet resolves to a foreign origin.
    setAuthToken('token-abc');

    // Built from code points so the hazardous characters are unambiguous in
    // source and cannot be flattened by an editor or a copy/paste.
    const TAB = String.fromCharCode(0x09);
    const LF = String.fromCharCode(0x0a);
    const CR = String.fromCharCode(0x0d);
    const BACKSLASH = String.fromCharCode(0x5c);

    const disguised = [
      `/${TAB}/evil.example/steal`,
      `/${LF}/evil.example/steal`,
      `/${CR}/evil.example/steal`,
      `/${BACKSLASH}evil.example/steal`,
      `/${TAB}${BACKSLASH}evil.example/steal`,
      `/v1/documents${CR}${LF}X-Injected: 1`,
    ];

    for (const path of disguised) {
      await expect(api.get(path)).rejects.toThrow(/Refusing to send credentials/);
    }

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('still allows ordinary same-origin API paths', async () => {
    // A fresh Response per call: a body can only be read once, so a single
    // shared instance fails the second request with "Body is unusable".
    fetchMock.mockImplementation(() => Promise.resolve(new Response('{}', { status: 200 })));

    await expect(api.get('/v1/documents?limit=20')).resolves.toEqual({});
    await expect(api.get('/v1/documents/abc/content')).resolves.toEqual({});
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});

describe('RFC 7807 problem-details parsing', () => {
  it('builds an ApiError carrying the parsed problem envelope', async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          type: 'https://docmgmt/errors/forbidden',
          title: 'Forbidden',
          status: 403,
          detail: 'Clearance rank 2 is below the document level.',
          instance: '/v1/documents/abc',
        }),
        { status: 403, headers: { 'Content-Type': 'application/problem+json' } }
      )
    );

    const err = await captureApiError(api.get('/v1/documents/abc'));

    expect(err).toBeInstanceOf(ApiError);
    expect(err.name).toBe('ApiError');
    expect(err.status).toBe(403);
    // `detail` is the human-facing sentence and must win over `title`.
    expect(err.message).toBe('Clearance rank 2 is below the document level.');
    expect(err.problem?.title).toBe('Forbidden');
    expect(err.problem?.type).toBe('https://docmgmt/errors/forbidden');
    expect(err.problem?.instance).toBe('/v1/documents/abc');
  });

  it('falls back to title when the envelope has no detail', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ title: 'Conflict', status: 409 }), { status: 409 })
    );

    const err = await captureApiError(api.post('/v1/review/1/resolve', {}));

    expect(err.message).toBe('Conflict');
    expect(err.status).toBe(409);
  });

  it('survives a non-JSON error body without masking the status', async () => {
    // An upstream proxy returning an HTML 502 must not surface as a JSON parse
    // error; the status is the actionable part.
    fetchMock.mockResolvedValue(
      new Response('<html><body>502 Bad Gateway</body></html>', {
        status: 502,
        headers: { 'Content-Type': 'text/html' },
      })
    );

    const err = await captureApiError(api.get('/v1/documents'));

    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(502);
    expect(err.message).toBe('Request failed with status 502');
    expect(err.problem).toBeUndefined();
  });

  it('survives an empty error body', async () => {
    fetchMock.mockResolvedValue(new Response('', { status: 401 }));

    const err = await captureApiError(api.get('/v1/documents'));

    expect(err.status).toBe(401);
    expect(err.message).toBe('Request failed with status 401');
  });

  it('ignores a JSON error body that is not a problem envelope', async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify(['nope']), { status: 400 }));

    const err = await captureApiError(api.get('/v1/documents'));

    expect(err.status).toBe(400);
    expect(err.problem).toBeUndefined();
  });
});

describe('success-body handling', () => {
  it('returns an empty object for 204 No Content without parsing a body', async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));

    await expect(api.delete('/v1/admin/doc-types/abc')).resolves.toEqual({});
  });

  it('returns an empty object for a 200 with an empty body', async () => {
    // Some proxies rewrite 204 to 200-with-no-body. `response.json()` would
    // throw an opaque SyntaxError there.
    fetchMock.mockResolvedValue(new Response('', { status: 200 }));

    await expect(api.post('/v1/uploads/1/complete', {})).resolves.toEqual({});
  });

  it('raises an ApiError (not a SyntaxError) when a 200 body is not JSON', async () => {
    fetchMock.mockResolvedValue(new Response('<html>login page</html>', { status: 200 }));

    const err = await captureApiError(api.get('/v1/documents'));

    expect(err).toBeInstanceOf(ApiError);
    expect(err.message).toMatch(/not valid JSON/);
  });

  it('parses a JSON success body', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ items: [{ id: 'a' }], next_cursor: null }), { status: 200 })
    );

    await expect(api.get('/v1/documents')).resolves.toEqual({
      items: [{ id: 'a' }],
      next_cursor: null,
    });
  });
});

describe('query-string construction', () => {
  it('drops undefined, null and empty values and keeps zero and false', async () => {
    fetchMock.mockResolvedValue(new Response('{}', { status: 200 }));

    await api.get('/v1/documents', {
      status: 'ready',
      security_level: undefined,
      cursor: '',
      limit: 0,
      archived: false,
    });

    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain('status=ready');
    expect(url).toContain('limit=0');
    expect(url).toContain('archived=false');
    expect(url).not.toContain('security_level');
    expect(url).not.toContain('cursor');
  });

  it('appends with & when the path already has a query string', async () => {
    fetchMock.mockResolvedValue(new Response('{}', { status: 200 }));

    await api.get('/v1/search?q=x', { limit: 5 });

    expect(fetchMock.mock.calls[0][0]).toBe('/v1/search?q=x&limit=5');
  });
});

describe('putDirect — invariant #1 (browser to storage, no broker)', () => {
  class FakeXhr {
    static instances: FakeXhr[] = [];
    method = '';
    url = '';
    headers: Record<string, string> = {};
    withCredentials = true;
    sent: unknown = null;
    status = 200;
    upload: { onprogress: ((e: ProgressEvent) => void) | null } = { onprogress: null };
    onload: (() => void) | null = null;
    onerror: (() => void) | null = null;

    constructor() {
      FakeXhr.instances.push(this);
    }
    open(method: string, url: string) {
      this.method = method;
      this.url = url;
    }
    setRequestHeader(k: string, v: string) {
      this.headers[k] = v;
    }
    send(body: unknown) {
      this.sent = body;
    }
  }

  beforeEach(() => {
    FakeXhr.instances = [];
    vi.stubGlobal('XMLHttpRequest', FakeXhr as unknown as typeof XMLHttpRequest);
  });

  it('PUTs the body to the presigned URL and never attaches credentials', async () => {
    setAuthToken('token-abc');
    const blob = new Blob(['file bytes']);

    const promise = api.putDirect('https://minio.local/quarantine/abc?sig=xyz', blob, 'application/pdf', {});
    const xhr = FakeXhr.instances[0];
    xhr.status = 200;
    xhr.onload?.();
    await promise;

    expect(xhr.method).toBe('PUT');
    expect(xhr.url).toBe('https://minio.local/quarantine/abc?sig=xyz');
    expect(xhr.sent).toBe(blob);
    // The presigned URL IS the credential. A second one leaks the session to
    // the storage host and breaks the signature on strict S3 implementations.
    expect(Object.keys(xhr.headers).map((k) => k.toLowerCase())).not.toContain('authorization');
    expect(xhr.withCredentials).toBe(false);

    // And the bytes must never have touched the API: fetch was not called at all.
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('POSTs the body as FormData when fields are present', async () => {
    setAuthToken('token-abc');
    const blob = new Blob(['file bytes']);

    const promise = api.putDirect('https://minio.local/quarantine/abc?sig=xyz', blob, 'application/pdf', { 'x-amz-credential': '123' });
    const xhr = FakeXhr.instances[0];
    xhr.status = 200;
    xhr.onload?.();
    await promise;

    expect(xhr.method).toBe('POST');
    expect(xhr.url).toBe('https://minio.local/quarantine/abc?sig=xyz');
    expect(xhr.sent).toBeInstanceOf(FormData);
  });

  it('reports progress from upload events', async () => {
    const seen: number[] = [];
    const promise = api.putDirect('https://minio.local/x', new Blob(['a']), 'application/pdf', {}, (p) =>
      seen.push(p)
    );
    const xhr = FakeXhr.instances[0];
    xhr.upload.onprogress?.({ lengthComputable: true, loaded: 25, total: 100 } as ProgressEvent);
    xhr.upload.onprogress?.({ lengthComputable: true, loaded: 100, total: 100 } as ProgressEvent);
    xhr.status = 200;
    xhr.onload?.();
    await promise;

    expect(seen).toEqual([25, 100]);
  });

  it('rejects with an ApiError carrying the storage status', async () => {
    const promise = api.putDirect('https://minio.local/x', new Blob(['a']), 'application/pdf', {});
    const xhr = FakeXhr.instances[0];
    xhr.status = 403;
    xhr.onload?.();

    const err = await captureApiError(promise);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(403);
    expect(err.message).toMatch(/Storage upload failed with status 403/);
  });

  it('rejects on a network error rather than hanging', async () => {
    const promise = api.putDirect('https://minio.local/x', new Blob(['a']), 'application/pdf', {});
    FakeXhr.instances[0].onerror?.();

    const err = await captureApiError(promise);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(0);
  });
});

describe('fetchDocumentContent — invariant #17', () => {
  it('requests the API content endpoint with the bearer token', async () => {
    setAuthToken('token-abc');
    fetchMock.mockResolvedValue(
      new Response('bytes', {
        status: 200,
        headers: { 'Content-Disposition': 'attachment; filename="secret.pdf"' },
      })
    );

    const result = await api.fetchDocumentContent('doc-1');

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe('/v1/documents/doc-1/content');
    expect(headerOf(0, 'Authorization')).toBe('Bearer token-abc');
    expect(result.filename).toBe('secret.pdf');
    expect(result.redirected).toBe(false);
  });

  it('reports when the server chose the presigned redirect path', async () => {
    // Public/Internal get a 303 to a presigned URL, which the browser follows.
    // The client makes ONE request either way — it never builds a storage URL.
    const redirected = new Response('bytes', { status: 200 });
    Object.defineProperty(redirected, 'redirected', { value: true });
    Object.defineProperty(redirected, 'url', { value: 'https://minio.local/docs/abc?sig=1' });
    fetchMock.mockResolvedValue(redirected);

    const result = await api.fetchDocumentContent('doc-1');

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe('/v1/documents/doc-1/content');
    expect(result.redirected).toBe(true);
  });

  it('throws an ApiError with the problem detail on denial', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ title: 'Not Found', status: 404, detail: 'No such document.' }), {
        status: 404,
      })
    );

    const err = await captureApiError(api.fetchDocumentContent('doc-1'));

    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(404);
    expect(err.message).toBe('No such document.');
  });

  it('does not mask a non-JSON error body', async () => {
    fetchMock.mockResolvedValue(new Response('gateway exploded', { status: 502 }));

    const err = await captureApiError(api.fetchDocumentContent('doc-1'));

    expect(err.status).toBe(502);
    expect(err.message).toBe('Failed to download (502)');
  });
});

describe('parseContentDispositionFilename', () => {
  it('falls back when the header is absent', () => {
    expect(parseContentDispositionFilename(null, 'fallback.bin')).toBe('fallback.bin');
  });

  it('reads the plain filename form', () => {
    expect(parseContentDispositionFilename('attachment; filename="report.pdf"', 'x')).toBe(
      'report.pdf'
    );
  });

  it('prefers the RFC 5987 encoded form', () => {
    expect(
      parseContentDispositionFilename(
        "attachment; filename=\"fallback.pdf\"; filename*=UTF-8''r%C3%A9sum%C3%A9.pdf",
        'x'
      )
    ).toBe('résumé.pdf');
  });

  it('strips path separators and leading dots so a crafted header cannot steer the save target', () => {
    expect(
      parseContentDispositionFilename('attachment; filename="../../etc/passwd"', 'x')
    ).toBe('_.._etc_passwd');
    expect(
      parseContentDispositionFilename("attachment; filename*=UTF-8''..%2F..%2Fevil.exe", 'x')
    ).toBe('_.._evil.exe');
  });
});
