import React from 'react';
import { Badge } from '../ui/badge';
import { SecurityLevelName } from '../../api/types';
import { LEVEL_RANK } from '../../security/levels';
import { ShieldCheck, ShieldAlert, Lock, Globe } from 'lucide-react';

interface LevelBadgeProps {
  level?: SecurityLevelName | string | null;
  rank?: number | null;
  className?: string;
  showIcon?: boolean;
}

/** Lowercase lookup key. `SecurityLevelName` is the capitalised wire form. */
type LevelKey = 'public' | 'internal' | 'confidential' | 'restricted';

const RANK_TO_NAME: Record<number, LevelKey> = {
  1: 'public',
  2: 'internal',
  3: 'confidential',
  4: 'restricted',
};

/**
 * Resolve the label to display, flooring at Internal (invariant #9).
 *
 * The previous fallback chain ended in `'public'`, so a document with a null or
 * unrecognised level — an unclassified upload, or one whose classification has
 * not landed yet — was rendered with the LEAST sensitive badge in the system.
 * Absence of a label means "not yet known", never "safe to share".
 */
function resolveLevel(
  level?: SecurityLevelName | string | null,
  rank?: number | null
): LevelKey {
  const fromName = level ? RANK_TO_NAME[LEVEL_RANK[level.toLowerCase()]] : undefined;
  if (fromName) return fromName;
  if (rank != null && RANK_TO_NAME[rank]) return RANK_TO_NAME[rank];
  return 'internal';
}

export const LevelBadge: React.FC<LevelBadgeProps> = ({
  level,
  rank,
  className,
  showIcon = true,
}) => {
  const norm = resolveLevel(level, rank);

  const icons = {
    public: <Globe className="w-3 h-3 mr-1" />,
    internal: <ShieldCheck className="w-3 h-3 mr-1" />,
    confidential: <Lock className="w-3 h-3 mr-1" />,
    restricted: <ShieldAlert className="w-3 h-3 mr-1" />,
  };

  const labels = {
    public: 'Public',
    internal: 'Internal',
    confidential: 'Confidential',
    restricted: 'Restricted',
  };

  return (
    <Badge variant={norm as any} className={className}>
      {showIcon && ((icons as any)[norm] || <ShieldCheck className="w-3 h-3 mr-1" />)}
      {(labels as any)[norm] || norm}
    </Badge>
  );
};
