import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { api } from '../../api/client';
import { DocumentStatsOut } from '../../api/types';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../../components/ui/card';
import { Button } from '../../components/ui/button';
import { LevelBadge } from '../../components/common/LevelBadge';
import { ProblemAlert } from '../../components/common/ProblemAlert';
import { DocumentDrawer } from '../documents/DocumentDrawer';
import { formatBytes, formatDate } from '../../lib/utils';
import { usePermissions } from '../../security/usePermissions';
import { Action } from '../../security/permissions';
import {
  FileText,
  Shield,
  ShieldAlert,
  CheckCircle2,
  Clock,
  AlertTriangle,
  XCircle,
  HardDrive,
  Building2,
  TrendingUp,
  Layers,
  RefreshCw,
  ArrowRight,
  UploadCloud,
  CheckSquare,
  BarChart3,
  Cpu,
} from 'lucide-react';

const LEVEL_COLORS: Record<string, { bg: string; bar: string; text: string; border: string }> = {
  Public: {
    bg: 'bg-[#dafbe1] dark:bg-[#1f883d]/20',
    bar: 'bg-[#1a7f37] dark:bg-[#3fb950]',
    text: 'text-[#1a7f37] dark:text-[#3fb950]',
    border: 'border-[#4ac26b]/40',
  },
  Internal: {
    bg: 'bg-[#ddf4ff] dark:bg-[#1f6feb]/20',
    bar: 'bg-[#0969da] dark:bg-[#2f81f7]',
    text: 'text-[#0969da] dark:text-[#2f81f7]',
    border: 'border-[#54aeff]/40',
  },
  Confidential: {
    bg: 'bg-[#fff8c5] dark:bg-[#9e6a03]/20',
    bar: 'bg-[#9a6700] dark:bg-[#d4a72c]',
    text: 'text-[#9a6700] dark:text-[#d4a72c]',
    border: 'border-[#d4a72c]/40',
  },
  Restricted: {
    bg: 'bg-[#ffebe9] dark:bg-[#da3633]/20',
    bar: 'bg-[#cf222e] dark:bg-[#f85149]',
    text: 'text-[#cf222e] dark:text-[#f85149]',
    border: 'border-[#ff8182]/40',
  },
};

export const DashboardPage: React.FC = () => {
  const navigate = useNavigate();
  const { can } = usePermissions();
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null);

  const {
    data: stats,
    isLoading,
    isError,
    error,
    refetch,
    isFetching,
  } = useQuery({
    queryKey: ['document-stats'],
    queryFn: () => api.get<DocumentStatsOut>('/v1/documents/stats'),
    refetchInterval: 30000,
  });

  const totalDocs = stats?.total_documents || 0;
  const readyDocs = stats?.status_breakdown.ready || 0;
  const readyPercent = totalDocs > 0 ? Math.round((readyDocs / totalDocs) * 100) : 100;
  const restrictedDocs = stats?.levels_breakdown.find((l) => l.name === 'Restricted')?.count || 0;
  const confidentialDocs = stats?.levels_breakdown.find((l) => l.name === 'Confidential')?.count || 0;

  return (
    <div className="space-y-6 max-w-6xl pb-8" data-testid="dashboard-page">
      {/* Header & Quick Action Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-[#d0d7de] dark:border-[#30363d]">
        <div>
          <div className="flex items-center gap-2">
            <BarChart3 className="w-5 h-5 text-[#0969da] dark:text-[#2f81f7]" />
            <h1 className="text-xl font-bold text-[#1f2328] dark:text-[#e6edf3] tracking-tight">
              Repository & Document Intelligence
            </h1>
          </div>
          <p className="text-xs text-[#656d76] dark:text-[#848d97] mt-0.5">
            Real-time telemetry, classification distributions, processing health, and access scope.
          </p>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          <Button
            variant="outline"
            size="sm"
            onClick={() => refetch()}
            disabled={isFetching}
            className="text-xs"
            aria-label="Refresh dashboard data"
          >
            <RefreshCw className={`w-3.5 h-3.5 mr-1.5 ${isFetching ? 'animate-spin' : ''}`} />
            Refresh
          </Button>

          {can(Action.UPLOAD) && (
            <Button
              variant="default"
              size="sm"
              onClick={() => navigate('/upload')}
              className="text-xs"
            >
              <UploadCloud className="w-3.5 h-3.5 mr-1.5" />
              Upload New
            </Button>
          )}

          {can(Action.RESOLVE_REVIEW) && (stats?.pending_reviews_count || 0) > 0 && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => navigate('/review')}
              className="text-xs bg-[#fff8c5] dark:bg-[#9e6a03]/20 border-[#d4a72c]/50 text-[#9a6700] dark:text-[#f2cc60]"
            >
              <CheckSquare className="w-3.5 h-3.5 mr-1.5" />
              Review Queue ({stats?.pending_reviews_count})
            </Button>
          )}
        </div>
      </div>

      <ProblemAlert error={isError ? error : null} />

      {/* Top Row: Metric KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3.5">
        {/* Total Documents */}
        <Card className="relative overflow-hidden">
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-[#656d76] dark:text-[#848d97]">
                Total Documents
              </span>
              <span className="p-2 rounded-md bg-[#ddf4ff] dark:bg-[#1f6feb]/20 text-[#0969da] dark:text-[#2f81f7]">
                <FileText className="w-4 h-4" />
              </span>
            </div>
            <div className="mt-2 flex items-baseline gap-2">
              <span className="text-2xl font-bold text-[#1f2328] dark:text-[#e6edf3]">
                {isLoading ? '...' : totalDocs.toLocaleString()}
              </span>
              <span className="text-[11px] font-medium text-[#1a7f37] dark:text-[#3fb950] flex items-center">
                <CheckCircle2 className="w-3 h-3 mr-0.5 inline" /> {readyPercent}% ready
              </span>
            </div>
            <p className="text-[10px] text-[#656d76] dark:text-[#848d97] mt-1">
              Scoped to your clearance & department access
            </p>
          </CardContent>
        </Card>

        {/* High Security Corpus */}
        <Card className="relative overflow-hidden">
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-[#656d76] dark:text-[#848d97]">
                Restricted & Confidential
              </span>
              <span className="p-2 rounded-md bg-[#ffebe9] dark:bg-[#da3633]/20 text-[#cf222e] dark:text-[#f85149]">
                <ShieldAlert className="w-4 h-4" />
              </span>
            </div>
            <div className="mt-2 flex items-baseline gap-2">
              <span className="text-2xl font-bold text-[#cf222e] dark:text-[#f85149]">
                {isLoading ? '...' : (restrictedDocs + confidentialDocs).toLocaleString()}
              </span>
              <span className="text-[11px] text-[#656d76] dark:text-[#848d97]">
                ({restrictedDocs} Restricted / {confidentialDocs} Conf.)
              </span>
            </div>
            <p className="text-[10px] text-[#656d76] dark:text-[#848d97] mt-1">
              PII / Sensitive items requiring elevated clearance
            </p>
          </CardContent>
        </Card>

        {/* Pipeline & Queue */}
        <Card className="relative overflow-hidden">
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-[#656d76] dark:text-[#848d97]">
                Pending Human Review
              </span>
              <span className="p-2 rounded-md bg-[#fff8c5] dark:bg-[#9e6a03]/20 text-[#9a6700] dark:text-[#d4a72c]">
                <Clock className="w-4 h-4" />
              </span>
            </div>
            <div className="mt-2 flex items-baseline gap-2">
              <span className="text-2xl font-bold text-[#1f2328] dark:text-[#e6edf3]">
                {isLoading ? '...' : (stats?.pending_reviews_count || 0).toLocaleString()}
              </span>
              {(stats?.pending_reviews_count || 0) > 0 ? (
                <span className="text-[11px] text-[#9a6700] dark:text-[#f2cc60] font-semibold">
                  Action required
                </span>
              ) : (
                <span className="text-[11px] text-[#1a7f37] dark:text-[#3fb950] font-medium">
                  Queue clear
                </span>
              )}
            </div>
            <p className="text-[10px] text-[#656d76] dark:text-[#848d97] mt-1">
              Low-confidence ML/LLM cascade predictions
            </p>
          </CardContent>
        </Card>

        {/* Total Storage */}
        <Card className="relative overflow-hidden">
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-[#656d76] dark:text-[#848d97]">
                Total Stored Volume
              </span>
              <span className="p-2 rounded-md bg-[#f6f8fa] dark:bg-[#21262d] text-[#656d76] dark:text-[#848d97]">
                <HardDrive className="w-4 h-4" />
              </span>
            </div>
            <div className="mt-2 flex items-baseline gap-2">
              <span className="text-2xl font-bold text-[#1f2328] dark:text-[#e6edf3]">
                {isLoading ? '...' : formatBytes(stats?.total_storage_bytes || 0)}
              </span>
              {stats?.avg_confidence !== null && stats?.avg_confidence !== undefined && (
                <span className="text-[11px] text-[#1a7f37] dark:text-[#3fb950]">
                  {(stats.avg_confidence * 100).toFixed(1)}% avg conf.
                </span>
              )}
            </div>
            <p className="text-[10px] text-[#656d76] dark:text-[#848d97] mt-1">
              Content-addressed deduplicated blobs
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Middle Row: Security Level Distribution & Document Types */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Security Level Distribution Graph */}
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="flex items-center gap-2">
                <Shield className="w-4 h-4 text-[#0969da] dark:text-[#2f81f7]" />
                Security Level Distribution
              </CardTitle>
              <span className="text-[10px] font-mono text-[#656d76] dark:text-[#848d97]">
                Monotonic Hierarchy
              </span>
            </div>
            <CardDescription>
              Breakdown of security clearance levels across repository documents.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {/* Visual Multi-Segment Proportion Bar */}
            <div className="w-full h-3 rounded-full bg-[#eaeef2] dark:bg-[#21262d] overflow-hidden flex shadow-inner">
              {stats?.levels_breakdown.map((level) => {
                const colors = LEVEL_COLORS[level.name] || LEVEL_COLORS.Internal;
                if (level.percentage <= 0) return null;
                return (
                  <div
                    key={level.name}
                    style={{ width: `${level.percentage}%` }}
                    className={`${colors.bar} h-full transition-all duration-500`}
                    title={`${level.name}: ${level.count} (${level.percentage}%)`}
                  />
                );
              })}
            </div>

            {/* Level Breakdown Cards */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              {stats?.levels_breakdown.map((level) => {
                const colors = LEVEL_COLORS[level.name] || LEVEL_COLORS.Internal;
                return (
                  <div
                    key={level.name}
                    className={`p-2.5 rounded-md border ${colors.border} ${colors.bg} flex flex-col justify-between`}
                  >
                    <div className="flex items-center justify-between">
                      <span className={`text-[11px] font-bold ${colors.text}`}>
                        {level.name}
                      </span>
                      <span className="text-[10px] font-mono text-[#656d76] dark:text-[#848d97]">
                        Rank {level.rank}
                      </span>
                    </div>
                    <div className="mt-2 flex items-baseline justify-between">
                      <span className="text-lg font-bold text-[#1f2328] dark:text-[#e6edf3]">
                        {level.count}
                      </span>
                      <span className="text-[10px] font-medium text-[#656d76] dark:text-[#848d97]">
                        {level.percentage}%
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Decision Engine Breakdown Footer */}
            <div className="pt-2 border-t border-[#d0d7de] dark:border-[#30363d] flex items-center justify-between flex-wrap gap-2 text-[11px] text-[#656d76] dark:text-[#848d97]">
              <span className="flex items-center gap-1 font-medium">
                <Cpu className="w-3.5 h-3.5 text-[#0969da] dark:text-[#2f81f7]" /> Decision Sources:
              </span>
              <div className="flex items-center gap-2">
                {stats?.decision_sources.map((src) => (
                  <span
                    key={src.source}
                    className="px-1.5 py-0.5 rounded text-[10px] font-mono uppercase bg-[#f6f8fa] dark:bg-[#21262d] border border-[#d0d7de] dark:border-[#30363d]"
                  >
                    {src.source}: <strong className="text-[#1f2328] dark:text-[#e6edf3]">{src.count}</strong>
                  </span>
                ))}
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Document Types Distribution */}
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="flex items-center gap-2">
                <Layers className="w-4 h-4 text-[#1a7f37] dark:text-[#3fb950]" />
                Document Types Taxonomy
              </CardTitle>
              <span className="text-[10px] font-mono text-[#656d76] dark:text-[#848d97]">
                Cascade Classification
              </span>
            </div>
            <CardDescription>
              Distribution of categorized document types in the active repository.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {stats && stats.doc_types_breakdown.length > 0 ? (
              <div className="space-y-2.5">
                {stats.doc_types_breakdown.map((dt) => (
                  <div key={dt.name} className="space-y-1">
                    <div className="flex justify-between text-xs">
                      <span className="font-semibold text-[#1f2328] dark:text-[#e6edf3]">
                        {dt.name}
                      </span>
                      <span className="text-[#656d76] dark:text-[#848d97] font-mono">
                        {dt.count} docs ({dt.percentage}%)
                      </span>
                    </div>
                    <div className="w-full h-2 rounded-full bg-[#eaeef2] dark:bg-[#21262d] overflow-hidden">
                      <div
                        style={{ width: `${Math.max(dt.percentage, 3)}%` }}
                        className="h-full bg-[#1a7f37] dark:bg-[#3fb950] rounded-full transition-all duration-500"
                      />
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-[#656d76] dark:text-[#848d97] py-6 text-center">
                No classified document types available yet.
              </p>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Row 3: Processing Pipeline Health & Department Distribution */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Processing Pipeline Status Breakdown */}
        <Card className="lg:col-span-1">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2">
              <TrendingUp className="w-4 h-4 text-[#0969da] dark:text-[#2f81f7]" />
              Processing Pipeline Health
            </CardTitle>
            <CardDescription>
              State of malware scanning, OCR extraction, and embedding jobs.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-2.5">
            <div className="flex items-center justify-between p-2 rounded-md bg-[#dafbe1]/60 dark:bg-[#1f883d]/10 border border-[#4ac26b]/30">
              <div className="flex items-center gap-2 text-xs font-semibold text-[#1a7f37] dark:text-[#3fb950]">
                <CheckCircle2 className="w-4 h-4" /> Ready & Active
              </div>
              <span className="text-sm font-bold text-[#1f2328] dark:text-[#e6edf3]">
                {stats?.status_breakdown.ready || 0}
              </span>
            </div>

            <div className="flex items-center justify-between p-2 rounded-md bg-[#ddf4ff]/60 dark:bg-[#1f6feb]/10 border border-[#54aeff]/30">
              <div className="flex items-center gap-2 text-xs font-semibold text-[#0969da] dark:text-[#2f81f7]">
                <RefreshCw className="w-4 h-4 animate-spin" /> Ingesting / Processing
              </div>
              <span className="text-sm font-bold text-[#1f2328] dark:text-[#e6edf3]">
                {stats?.status_breakdown.processing || 0}
              </span>
            </div>

            <div className="flex items-center justify-between p-2 rounded-md bg-[#fff8c5]/60 dark:bg-[#9e6a03]/10 border border-[#d4a72c]/30">
              <div className="flex items-center gap-2 text-xs font-semibold text-[#9a6700] dark:text-[#d4a72c]">
                <AlertTriangle className="w-4 h-4" /> Held / Quarantined
              </div>
              <span className="text-sm font-bold text-[#1f2328] dark:text-[#e6edf3]">
                {(stats?.status_breakdown.held || 0) + (stats?.status_breakdown.quarantined || 0)}
              </span>
            </div>

            <div className="flex items-center justify-between p-2 rounded-md bg-[#ffebe9]/60 dark:bg-[#da3633]/10 border border-[#ff8182]/30">
              <div className="flex items-center gap-2 text-xs font-semibold text-[#cf222e] dark:text-[#f85149]">
                <XCircle className="w-4 h-4" /> Failed / Error
              </div>
              <span className="text-sm font-bold text-[#1f2328] dark:text-[#e6edf3]">
                {stats?.status_breakdown.failed || 0}
              </span>
            </div>
          </CardContent>
        </Card>

        {/* Department Volume Distribution */}
        <Card className="lg:col-span-1">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2">
              <Building2 className="w-4 h-4 text-[#656d76] dark:text-[#848d97]" />
              Department Visibility
            </CardTitle>
            <CardDescription>
              Documents partitioned across accessible organizational units.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {stats && stats.departments_breakdown.length > 0 ? (
              <div className="space-y-2">
                {stats.departments_breakdown.map((dept) => (
                  <div
                    key={dept.id}
                    className="flex items-center justify-between p-2 rounded-md bg-[#f6f8fa] dark:bg-[#161b22] border border-[#d0d7de] dark:border-[#30363d] text-xs"
                  >
                    <div className="flex items-center gap-2 font-medium text-[#1f2328] dark:text-[#e6edf3]">
                      <Building2 className="w-3.5 h-3.5 text-[#656d76] dark:text-[#848d97]" />
                      {dept.name}
                    </div>
                    <span className="font-mono font-bold text-xs bg-white dark:bg-[#0d1117] px-2 py-0.5 rounded border border-[#d0d7de] dark:border-[#30363d] text-[#1f2328] dark:text-[#e6edf3]">
                      {dept.count}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-[#656d76] dark:text-[#848d97] py-6 text-center">
                All documents scoped tenant-wide.
              </p>
            )}
          </CardContent>
        </Card>

        {/* Ingestion Activity Sparkline / Days */}
        <Card className="lg:col-span-1">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2">
              <TrendingUp className="w-4 h-4 text-[#0969da] dark:text-[#2f81f7]" />
              Recent Ingestion Trend
            </CardTitle>
            <CardDescription>
              Volume of document uploads recorded over recent days.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {stats && stats.daily_ingestion.length > 0 ? (
              <div className="space-y-2">
                <div className="flex items-end gap-1.5 h-24 pt-4 px-1">
                  {stats.daily_ingestion.map((day) => {
                    const maxCount = Math.max(...stats.daily_ingestion.map((d) => d.count), 1);
                    const heightPercent = Math.max(Math.round((day.count / maxCount) * 100), 15);
                    return (
                      <div
                        key={day.date}
                        className="flex-1 flex flex-col items-center gap-1 group relative h-full justify-end"
                      >
                        <div
                          style={{ height: `${heightPercent}%` }}
                          className="w-full bg-[#0969da] dark:bg-[#1f6feb] rounded-t-sm hover:opacity-80 transition-all cursor-default"
                        />
                        <span className="text-[8px] text-[#656d76] dark:text-[#848d97] font-mono truncate max-w-full">
                          {day.date.slice(5)}
                        </span>
                        {/* Hover Tooltip */}
                        <div className="absolute -top-7 hidden group-hover:block bg-[#1f2328] text-white text-[9px] px-1.5 py-0.5 rounded shadow whitespace-nowrap z-10">
                          {day.date}: {day.count} docs
                        </div>
                      </div>
                    );
                  })}
                </div>
                <div className="flex justify-between text-[10px] text-[#656d76] dark:text-[#848d97] pt-2 border-t border-[#d0d7de] dark:border-[#30363d]">
                  <span>Daily ingestion volume</span>
                  <span>{stats.daily_ingestion.reduce((acc, curr) => acc + curr.count, 0)} total</span>
                </div>
              </div>
            ) : (
              <p className="text-xs text-[#656d76] dark:text-[#848d97] py-6 text-center">
                No recent ingestion records.
              </p>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Row 4: Recent Documents Table */}
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="flex items-center gap-2">
                <Clock className="w-4 h-4 text-[#0969da] dark:text-[#2f81f7]" />
                Recently Ingested Documents
              </CardTitle>
              <CardDescription>
                Latest documents processed and classified in the system.
              </CardDescription>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={() => navigate('/documents')}
              className="text-xs"
            >
              View All Documents
              <ArrowRight className="w-3.5 h-3.5 ml-1" />
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {stats && stats.recent_documents.length > 0 ? (
            <div className="divide-y divide-[#d0d7de] dark:divide-[#30363d] overflow-hidden rounded-md border border-[#d0d7de] dark:border-[#30363d]">
              {stats.recent_documents.map((doc) => (
                <div
                  key={doc.id}
                  onClick={() => setSelectedDocId(doc.id)}
                  className="flex flex-col sm:flex-row sm:items-center justify-between p-3 gap-2 bg-white dark:bg-[#0d1117] hover:bg-[#f6f8fa] dark:hover:bg-[#161b22] transition-colors cursor-pointer"
                >
                  <div className="flex items-center gap-2.5 min-w-0">
                    <FileText className="w-4 h-4 text-[#0969da] dark:text-[#2f81f7] shrink-0" />
                    <div className="min-w-0">
                      <span className="font-semibold text-xs text-[#1f2328] dark:text-[#e6edf3] truncate block">
                        {doc.filename}
                      </span>
                      <span className="text-[10px] text-[#656d76] dark:text-[#848d97]">
                        Ingested {formatDate(doc.created_at)}
                      </span>
                    </div>
                  </div>

                  <div className="flex items-center gap-2 shrink-0">
                    {doc.doc_type && (
                      <span className="text-[11px] font-mono px-2 py-0.5 rounded bg-[#f6f8fa] dark:bg-[#21262d] border border-[#d0d7de] dark:border-[#30363d] text-[#1f2328] dark:text-[#e6edf3]">
                        {doc.doc_type}
                      </span>
                    )}
                    <LevelBadge level={doc.level || 'Internal'} />
                    <span
                      className={`text-[10px] font-bold px-2 py-0.5 rounded capitalize ${
                        doc.status === 'ready'
                          ? 'bg-[#dafbe1] dark:bg-[#1f883d]/20 text-[#1a7f37] dark:text-[#3fb950]'
                          : doc.status === 'processing'
                          ? 'bg-[#ddf4ff] dark:bg-[#1f6feb]/20 text-[#0969da] dark:text-[#2f81f7]'
                          : 'bg-[#ffebe9] dark:bg-[#da3633]/20 text-[#cf222e] dark:text-[#f85149]'
                      }`}
                    >
                      {doc.status}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-[#656d76] dark:text-[#848d97] py-6 text-center">
              No documents ingested yet.
            </p>
          )}
        </CardContent>
      </Card>

      {/* Drawer for document preview */}
      {selectedDocId && (
        <DocumentDrawer
          documentId={selectedDocId}
          onClose={() => setSelectedDocId(null)}
        />
      )}
    </div>
  );
};
