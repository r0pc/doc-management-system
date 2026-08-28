import { SecurityLevelName } from '../api/types';

/**
 * Ordinal ranks for the four security levels (AGENTS.md: Public -> Internal ->
 * Confidential -> Restricted, combined by maximum, monotonic upward).
 *
 * The backend seeds level names capitalised; several API payloads carry them
 * lowercased. Every comparison here normalises first — comparing the raw
 * strings is how a "Restricted" document silently gets treated as unknown.
 */
export const LEVEL_RANK: Record<string, number> = {
  public: 1,
  internal: 2,
  confidential: 3,
  restricted: 4,
};

/** Invariant #9: anything unrecognised floors at Internal, never Public. */
export const DEFAULT_FLOOR_RANK = LEVEL_RANK.internal;

export function levelRank(level: string | null | undefined): number {
  if (!level) return DEFAULT_FLOOR_RANK;
  return LEVEL_RANK[level.toLowerCase()] ?? DEFAULT_FLOOR_RANK;
}

/**
 * True when `next` sits strictly below `current` on the ordinal scale.
 *
 * This is a rank comparison, not a membership test. The previous
 * `['restricted','confidential'].includes(current) && ['public','internal'].includes(next)`
 * form missed Restricted -> Confidential and Internal -> Public entirely, so
 * two of the six possible downgrades produced no warning and no justification
 * prompt at all.
 */
export function isLoweringLevel(
  current: string | null | undefined,
  next: SecurityLevelName | string
): boolean {
  return levelRank(next) < levelRank(current);
}

/** Minimum length for a downgrade justification, so "ok" does not satisfy it. */
export const MIN_JUSTIFICATION_LENGTH = 10;

export function justificationIsSufficient(text: string): boolean {
  return text.trim().length >= MIN_JUSTIFICATION_LENGTH;
}
