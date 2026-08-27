import React from 'react';
import { Badge } from '../ui/badge';
import { SecurityLevelName } from '../../api/types';
import { ShieldCheck, ShieldAlert, Lock, Globe } from 'lucide-react';

interface LevelBadgeProps {
  level?: SecurityLevelName | string | null;
  rank?: number | null;
  className?: string;
  showIcon?: boolean;
}

export const LevelBadge: React.FC<LevelBadgeProps> = ({
  level,
  rank,
  className,
  showIcon = true,
}) => {
  const norm = (level || (rank === 4 ? 'restricted' : rank === 3 ? 'confidential' : rank === 2 ? 'internal' : 'public')).toLowerCase() as SecurityLevelName;

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
    <Badge variant={norm} className={className}>
      {showIcon && (icons[norm] || <ShieldCheck className="w-3 h-3 mr-1" />)}
      {labels[norm] || norm}
    </Badge>
  );
};
