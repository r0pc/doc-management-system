import { readFileSync, readdirSync } from 'node:fs';
import { join, extname } from 'node:path';

/**
 * Every API path the frontend actually calls, read out of the source.
 *
 * The deployment-freshness check used to compare the live API against a
 * hand-maintained array. That array is the thing that rots: `/v1/documents/delete`,
 * `/v1/documents/auto-classify` and `/v1/auth/login` were all added to the client
 * and never added to the list, so the guard built to catch a stale image sat
 * green while the running API was missing three routes the UI depends on. The
 * user found `auto-classify` by clicking the button and getting a 405.
 *
 * Deriving the list from the source removes the step a human has to remember.
 * A route the client calls is required by construction.
 */

const SRC = new URL('../../src', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1');

/** Paths that are legitimately absent from the running API, with the reason. */
const EXPECTED_ABSENT = new Set<string>([
  // Nothing at present. Add with a comment saying why, never to silence a
  // genuine miss — that is exactly how the previous list went stale.
]);

function sourceFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      out.push(...sourceFiles(full));
      continue;
    }
    // Tests carry fixture ids and deliberately malformed paths (the header
    // injection probe among them); they are not statements about the API.
    if (entry.name.includes('.test.')) continue;
    if (['.ts', '.tsx'].includes(extname(entry.name))) out.push(full);
  }
  return out;
}

/** Remove comments so prose about a route is not mistaken for a call. */
function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/.*$/gm, '$1');
}

/**
 * Reduce a path to its shape: every interpolated or named segment becomes `*`,
 * so `/v1/documents/${id}/jobs` and `/v1/documents/{document_id}/jobs` compare
 * equal.
 */
export function pathShape(path: string): string {
  return path
    .split('?')[0]
    .split('/')
    .map((segment) =>
      segment.includes('${') || /^\{.*\}$/.test(segment) ? '*' : segment
    )
    .join('/')
    .replace(/\/$/, '');
}

/** The distinct API path shapes the frontend calls. */
export function clientRouteShapes(): string[] {
  const found = new Set<string>();
  for (const file of sourceFiles(SRC)) {
    const source = stripComments(readFileSync(file, 'utf8'));
    for (const match of source.matchAll(/['"`](\/v1\/[^'"`]*)['"`]/g)) {
      const shape = pathShape(match[1]);
      // `/v1/` alone is the client's base-path guard, not a route.
      if (shape === '/v1' || shape === '') continue;
      if (EXPECTED_ABSENT.has(shape)) continue;
      found.add(shape);
    }
  }
  return [...found].sort();
}
