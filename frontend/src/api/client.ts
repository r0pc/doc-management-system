import { ProblemDetails } from './types';

export class ApiError extends Error {
  status: number;
  problem?: ProblemDetails;

  constructor(status: number, message: string, problem?: ProblemDetails) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.problem = problem;
  }
}

export const AUTH_TOKEN_STORAGE_KEY = 'dms_auth_token';

/**
 * Auth-token storage trade-off — read before changing this.
 *
 * The bearer token lives in `localStorage`. That is a deliberate, and imperfect,
 * choice for this deployment:
 *
 *  - COST: `localStorage` is readable by any JavaScript running on this origin.
 *    A single XSS — an injected script, a compromised npm dependency, a
 *    third-party widget — exfiltrates the token, and with it the user's full
 *    clearance for the token's lifetime (the dev shim mints 7-day tokens). An
 *    `HttpOnly; Secure; SameSite` cookie is the only storage the page's own
 *    JavaScript cannot read, and is therefore strictly safer against XSS.
 *  - BENEFIT: it is the only option that works with the current design, where
 *    the token is attached as an `Authorization: Bearer` header from fetch and
 *    the API is a separate origin behind a proxy. Cookie auth would require the
 *    backend to set the cookie, CSRF protection on every mutating route, and a
 *    same-site deployment — i.e. an auth re-architecture, not a frontend change.
 *  - CONSEQUENCE: the client-side token is NOT a security boundary. Every
 *    request is authorized server-side against the token's verified claims; a
 *    stolen token is contained by its TTL and by the audit trail, not by
 *    anything this file does.
 *
 * If this system moves to production auth (Keycloak/OIDC per AGENTS.md), move
 * the session to an HttpOnly cookie or a BFF and delete these helpers. Until
 * then, keep the token out of logs, URLs, and error payloads.
 *
 * Storage access is wrapped because it throws outright in Safari private mode
 * and when a browser is configured to block site data.
 */
export function getAuthToken(): string | null {
  try {
    return localStorage.getItem(AUTH_TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setAuthToken(token: string | null) {
  try {
    if (token) {
      localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, token);
    } else {
      localStorage.removeItem(AUTH_TOKEN_STORAGE_KEY);
    }
  } catch {
    // Storage unavailable (private mode / blocked site data). The token stays
    // in memory for this page only; the user re-authenticates on reload.
  }
}

/**
 * Every call through `request()` attaches the bearer token, so the target must
 * be the API origin and nothing else. Absolute URLs are refused outright: a
 * presigned storage URL, or any attacker-influenced host, must never receive an
 * `Authorization` header. Direct-to-storage traffic goes through `putDirect`,
 * which never sends credentials (invariant #1).
 */
/**
 * True when `path` contains a character that makes a naive string check and the
 * WHATWG URL parser disagree about where the authority begins.
 *
 * Written as a code-point scan rather than a regex so the two hazardous classes
 * are stated outright:
 *  - C0 controls and DEL: the parser STRIPS tab (0x09), LF (0x0A) and CR (0x0D)
 *    before parsing, so "/<TAB>/evil.com" becomes "//evil.com";
 *  - backslash (0x5C): for special schemes the parser treats it as "/", so
 *    "/\evil.com" reaches the authority state the same way.
 *
 * Both spellings satisfy `startsWith('//') === false`.
 */
function hasUrlParserHazard(path: string): boolean {
  for (let i = 0; i < path.length; i += 1) {
    const code = path.charCodeAt(i);
    if (code <= 0x1f || code === 0x7f || code === 0x5c) return true;
  }
  return false;
}

function assertApiPath(path: string): void {
  const reject = (): never => {
    throw new ApiError(
      0,
      `Refusing to send credentials to a non-API URL: ${path}. ` +
        'api.* takes a same-origin path such as "/v1/documents".'
    );
  };

  // Cheap shape check — necessary, but NOT the security boundary.
  if (!path.startsWith('/')) reject();

  // Refuse the divergent characters BEFORE parsing. This is deliberately not
  // left to the origin comparison below: URL implementations differ in how
  // faithfully they apply the stripping and backslash rules, and a lenient
  // parser paired with a strict network stack is exactly how this class of
  // bypass survives. Refusing outright is the same answer in every runtime.
  if (hasUrlParserHazard(path)) reject();

  // The boundary: resolve with the SAME parser `fetch` uses and compare
  // origins, which closes the whole class rather than the spellings we happened
  // to think of.
  let resolved: URL;
  try {
    resolved = new URL(path, window.location.origin);
  } catch {
    return reject();
  }
  if (resolved.origin !== window.location.origin) reject();
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  assertApiPath(path);

  const token = getAuthToken();
  const headers = new Headers(options.headers || {});

  if (token && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  if (!headers.has('Content-Type') && !(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }

  const response = await fetch(path, {
    ...options,
    headers,
  });

  if (!response.ok) {
    let problem: ProblemDetails | undefined;
    let message = `Request failed with status ${response.status}`;
    try {
      const data = await response.json();
      if (data && typeof data === 'object' && (data.title || data.detail || data.status)) {
        problem = data as ProblemDetails;
        message = problem.detail || problem.title || message;
      }
    } catch {
      // Body not JSON
    }
    throw new ApiError(response.status, message, problem);
  }

  // 204/205 carry no body by definition; a 200 with an empty body (some
  // proxies rewrite 204s) would otherwise blow up in `response.json()` with an
  // opaque SyntaxError instead of a usable result.
  if (response.status === 204 || response.status === 205) {
    return {} as T;
  }

  const text = await response.text();
  if (text === '') {
    return {} as T;
  }

  try {
    return JSON.parse(text) as T;
  } catch {
    throw new ApiError(
      response.status,
      `Expected JSON from ${path} but the response body was not valid JSON.`
    );
  }
}

export const api = {
  get: <T>(path: string, params?: Record<string, string | number | boolean | undefined>) => {
    let url = path;
    if (params) {
      const searchParams = new URLSearchParams();
      Object.entries(params).forEach(([key, val]) => {
        if (val !== undefined && val !== null && val !== '') {
          searchParams.append(key, String(val));
        }
      });
      const queryString = searchParams.toString();
      if (queryString) {
        url += (url.includes('?') ? '&' : '?') + queryString;
      }
    }
    return request<T>(url, { method: 'GET' });
  },

  post: <T>(path: string, body?: unknown) => {
    return request<T>(path, {
      method: 'POST',
      body: body ? JSON.stringify(body) : undefined,
    });
  },

  delete: <T>(path: string) => {
    return request<T>(path, { method: 'DELETE' });
  },

  // Direct PUT to presigned URL without Authorization header (Invariant #1)
  putDirect: async (
    url: string,
    file: Blob | ArrayBuffer,
    contentType: string,
    onProgress?: (percent: number) => void
  ): Promise<void> => {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('PUT', url, true);
      // Invariant #1: the bytes go browser -> object storage. No Authorization
      // header and no cookies are attached here — the presigned URL IS the
      // credential, and adding a second one would leak the session to the
      // storage host and break the signature on strict S3 implementations.
      xhr.withCredentials = false;
      xhr.setRequestHeader('Content-Type', contentType);

      if (xhr.upload && onProgress) {
        xhr.upload.onprogress = (e) => {
          if (e.lengthComputable) {
            const percent = Math.round((e.loaded / e.total) * 100);
            onProgress(percent);
          }
        };
      }

      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve();
        } else {
          reject(new ApiError(xhr.status, `Storage upload failed with status ${xhr.status}`));
        }
      };

      xhr.onerror = () => {
        reject(new ApiError(0, 'Storage upload network error'));
      };

      xhr.send(file);
    });
  },

  /**
   * Single entry point for document bytes (invariants #17 / #18).
   *
   * There is exactly ONE URL: the API's own `/v1/documents/{id}/content`. The
   * SERVER, not this client, decides the delivery mode from the document's
   * level — Confidential/Restricted stream through the API (one audit row per
   * response, range headers honoured), Public/Internal get a 303 to a
   * short-TTL presigned URL. The frontend never constructs, guesses, or
   * caches a storage URL, and never picks the "cheap" path for a restricted
   * document: it cannot, because it only knows one endpoint.
   *
   * On the 303 hop the browser drops the `Authorization` header (it is a
   * cross-origin redirect), so the bearer token is never presented to the
   * object store. `redirected` is returned so callers can *report* which path
   * the server chose; it is telemetry, never an authorization decision.
   */
  fetchDocumentContent: async (
    documentId: string
  ): Promise<{ blob: Blob; filename: string; redirected: boolean }> => {
    const token = getAuthToken();
    const headers: Record<string, string> = {};
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    const response = await fetch(`/v1/documents/${documentId}/content`, {
      method: 'GET',
      headers,
      redirect: 'follow',
    });

    if (!response.ok) {
      let problem: ProblemDetails | undefined;
      try {
        const data = await response.json();
        if (data && typeof data === 'object') {
          problem = data as ProblemDetails;
        }
      } catch {
        // Non-JSON error body (proxy HTML, empty 502). Fall through to the
        // status-only message rather than masking the failure.
      }
      throw new ApiError(
        response.status,
        problem?.detail || problem?.title || `Failed to download (${response.status})`,
        problem
      );
    }

    const blob = await response.blob();
    return {
      blob,
      filename: parseContentDispositionFilename(
        response.headers.get('Content-Disposition'),
        `document-${documentId}`
      ),
      redirected: response.redirected === true,
    };
  },
};

/**
 * The API pins `response-content-disposition` on presigned URLs, so this is the
 * server's filename, not user input from the current page. It is still treated
 * as untrusted: path separators are stripped so a crafted header can never
 * steer the browser's save target out of the download directory.
 */
export function parseContentDispositionFilename(
  disposition: string | null,
  fallback: string
): string {
  if (!disposition) return fallback;

  // RFC 5987 `filename*=UTF-8''...` wins over the plain form when both exist.
  const extended = disposition.match(/filename\*=(?:UTF-8|utf-8)''([^;]+)/);
  if (extended?.[1]) {
    try {
      const decoded = sanitizeFilename(decodeURIComponent(extended[1]));
      if (decoded) return decoded;
    } catch {
      // Malformed percent-encoding — fall through to the plain form.
    }
  }

  const plain = disposition.match(/filename=["']?([^"';]+)["']?/);
  if (plain?.[1]) {
    const cleaned = sanitizeFilename(plain[1]);
    if (cleaned) return cleaned;
  }

  return fallback;
}

function sanitizeFilename(name: string): string {
  return name.trim().replace(/[\\/]/g, '_').replace(/^\.+/, '');
}
