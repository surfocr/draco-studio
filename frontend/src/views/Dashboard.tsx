import React from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Images, CheckCircle, XCircle, Clock, FileText, Zap,
  Star, Users, Smile, BarChart2,
} from 'lucide-react'
import { useProjectStore } from '@/stores/useProjectStore'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, Cell,
  PieChart, Pie, ResponsiveContainer,
} from 'recharts'
import api from '@/hooks/useApi'

interface Stats {
  total: number
  approved: number
  rejected: number
  pending: number
  captioned: number
  caption_coverage_pct: number
  scored: number
  embedded: number
  avg_score: number
  high_quality: number
  low_quality: number
  score_histogram: { bucket: string; count: number }[]
  face_images: number
  multi_face: number
  shot_types: { type: string; count: number }[]
  emotions: { emotion: string; count: number }[]
}

const COLORS = ['#8b5cf6', '#6366f1', '#3b82f6', '#10b981', '#f59e0b', '#ef4444']

function StatCard({ icon: Icon, label, value, sub, color = 'violet' }: {
  icon: React.ElementType
  label: string
  value: string | number
  sub?: string
  color?: string
}) {
  const colorMap: Record<string, string> = {
    violet: 'text-violet-400 bg-violet-500/10',
    green: 'text-emerald-400 bg-emerald-500/10',
    red: 'text-red-400 bg-red-500/10',
    amber: 'text-amber-400 bg-amber-500/10',
    blue: 'text-blue-400 bg-blue-500/10',
  }
  const cls = colorMap[color] ?? colorMap.violet
  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4">
      <div className="flex items-start justify-between mb-3">
        <div className={`p-2 rounded-lg ${cls}`}>
          <Icon size={16} className={cls.split(' ')[0]} />
        </div>
      </div>
      <div className="text-2xl font-bold text-white tabular-nums">{value}</div>
      <div className="text-zinc-400 text-xs mt-0.5">{label}</div>
      {sub && <div className="text-zinc-600 text-xs mt-0.5">{sub}</div>}
    </div>
  )
}

function CoverageBar({ label, value, total, color }: {
  label: string
  value: number
  total: number
  color: string
}) {
  const pct = total > 0 ? (value / total) * 100 : 0
  return (
    <div>
      <div className="flex justify-between text-xs mb-1">
        <span className="text-zinc-400">{label}</span>
        <span className="text-zinc-300">
          {value} / {total}{' '}
          <span className="text-zinc-500">({pct.toFixed(0)}%)</span>
        </span>
      </div>
      <div className="h-2 bg-zinc-800 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

export function Dashboard() {
  const activeProject = useProjectStore((s) => s.activeProject)

  const { data: stats, isLoading } = useQuery<Stats>({
    queryKey: ['project-stats', activeProject?.id],
    queryFn: () =>
      api.get(`/api/projects/${activeProject!.id}/stats`).then((r) => r.data),
    enabled: !!activeProject,
    refetchInterval: 30_000,
  })

  if (!activeProject) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-4 text-zinc-500">
        <Images size={48} className="text-zinc-700" />
        <div className="text-center">
          <p className="text-lg font-medium text-zinc-400">No project selected</p>
          <p className="text-sm mt-1">Create or select a project to see your dataset stats</p>
        </div>
      </div>
    )
  }

  if (isLoading || !stats) {
    return (
      <div className="flex items-center justify-center h-full text-zinc-500 gap-2">
        <BarChart2 size={20} className="animate-pulse text-violet-400" />
        Loading stats...
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-y-auto p-6 bg-zinc-950">
      <div className="max-w-5xl mx-auto space-y-6">
        {/* Header */}
        <div>
          <h1 className="text-xl font-bold text-white">{activeProject.name}</h1>
          <p className="text-zinc-500 text-sm mt-0.5">Dataset overview</p>
        </div>

        {/* Quick stats grid */}
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
          <StatCard icon={Images} label="Total images" value={stats.total} color="violet" />
          <StatCard
            icon={CheckCircle}
            label="Approved"
            value={stats.approved}
            sub={`${stats.total > 0 ? Math.round((stats.approved / stats.total) * 100) : 0}% of dataset`}
            color="green"
          />
          <StatCard
            icon={FileText}
            label="Captioned"
            value={stats.captioned}
            sub={`${stats.caption_coverage_pct}% coverage`}
            color="blue"
          />
          <StatCard
            icon={Star}
            label="Avg score"
            value={`${Math.round(stats.avg_score * 100)}%`}
            sub={`${stats.high_quality} high quality`}
            color="amber"
          />
          <StatCard icon={XCircle} label="Rejected" value={stats.rejected} color="red" />
          <StatCard icon={Clock} label="Pending review" value={stats.pending} color="amber" />
          <StatCard
            icon={Users}
            label="With faces"
            value={stats.face_images}
            sub={`${stats.multi_face} multi-face`}
            color="violet"
          />
          <StatCard
            icon={Zap}
            label="Analyzed"
            value={stats.scored}
            sub={`${stats.total > 0 ? Math.round((stats.scored / stats.total) * 100) : 0}% scored`}
            color="green"
          />
        </div>

        {/* Coverage bars */}
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4 space-y-3">
          <h3 className="text-white text-sm font-semibold mb-3">Dataset Coverage</h3>
          <CoverageBar label="Approved" value={stats.approved} total={stats.total} color="bg-emerald-500" />
          <CoverageBar label="Captioned" value={stats.captioned} total={stats.total} color="bg-blue-500" />
          <CoverageBar label="Scored" value={stats.scored} total={stats.total} color="bg-violet-500" />
          <CoverageBar label="High quality (≥70%)" value={stats.high_quality} total={stats.total} color="bg-amber-500" />
        </div>

        {/* Charts row */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* Score histogram */}
          <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4">
            <h3 className="text-white text-sm font-semibold mb-3">Score Distribution</h3>
            <ResponsiveContainer width="100%" height={160}>
              <BarChart data={stats.score_histogram} margin={{ top: 0, right: 0, bottom: 0, left: -20 }}>
                <XAxis dataKey="bucket" tick={{ fontSize: 9, fill: '#71717a' }} tickLine={false} />
                <YAxis tick={{ fontSize: 9, fill: '#71717a' }} tickLine={false} axisLine={false} />
                <Tooltip
                  contentStyle={{
                    background: '#18181b',
                    border: '1px solid #3f3f46',
                    borderRadius: 8,
                    fontSize: 11,
                  }}
                  cursor={{ fill: 'rgba(139,92,246,0.1)' }}
                />
                <Bar dataKey="count" radius={[3, 3, 0, 0]}>
                  {stats.score_histogram.map((_, index) => (
                    <Cell key={index} fill={index >= 7 ? '#10b981' : index >= 4 ? '#f59e0b' : '#ef4444'} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>

          {/* Shot type breakdown */}
          {stats.shot_types.length > 0 && (
            <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4">
              <h3 className="text-white text-sm font-semibold mb-3">Shot Types</h3>
              <ResponsiveContainer width="100%" height={160}>
                <PieChart>
                  <Pie
                    data={stats.shot_types}
                    dataKey="count"
                    nameKey="type"
                    cx="50%"
                    cy="50%"
                    outerRadius={60}
                    paddingAngle={2}
                  >
                    {stats.shot_types.map((_, index) => (
                      <Cell key={index} fill={COLORS[index % COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip
                    contentStyle={{
                      background: '#18181b',
                      border: '1px solid #3f3f46',
                      borderRadius: 8,
                      fontSize: 11,
                    }}
                  />
                </PieChart>
              </ResponsiveContainer>
              <div className="flex flex-wrap gap-x-3 gap-y-1 mt-2">
                {stats.shot_types.map((st, i) => (
                  <div key={st.type} className="flex items-center gap-1 text-xs">
                    <div className="w-2 h-2 rounded-full" style={{ background: COLORS[i % COLORS.length] }} />
                    <span className="text-zinc-400 capitalize">{st.type}</span>
                    <span className="text-zinc-600">({st.count})</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Emotions */}
        {stats.emotions.length > 0 && (
          <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4">
            <h3 className="text-white text-sm font-semibold mb-3 flex items-center gap-2">
              <Smile size={14} className="text-violet-400" />
              Expression Breakdown
            </h3>
            <div className="flex flex-wrap gap-2">
              {stats.emotions.map((e, i) => (
                <div
                  key={e.emotion}
                  className="flex items-center gap-1.5 px-2.5 py-1.5 bg-zinc-800 rounded-lg border border-zinc-700"
                >
                  <div className="w-2 h-2 rounded-full" style={{ background: COLORS[i % COLORS.length] }} />
                  <span className="text-zinc-300 text-xs capitalize">{e.emotion}</span>
                  <span className="text-zinc-500 text-xs">{e.count}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
