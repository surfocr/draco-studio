import React, { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Wand2, Tag, CheckCircle, Loader2, Plus, Trash2, Play, Eye } from 'lucide-react'
import { useProjectStore } from '@/stores/useProjectStore'
import axios from 'axios'

const api = axios.create({ baseURL: import.meta.env.VITE_API_URL || 'http://localhost:18082' })

interface SortRule {
  id: string
  label: string
  description: string
  action: 'approve' | 'reject' | 'flag' | 'tag'
  tag?: string
  conditions: { field: string; op: string; value: any }[]
}

interface SortPreview {
  rule_label: string
  matched_count: number
  sample_filenames: string[]
  action: string
}

const PRESET_RULES: SortRule[] = [
  {
    id: 'remove_blurry',
    label: 'Reject blurry images',
    description: 'Technical quality below 30%',
    action: 'reject',
    conditions: [{ field: 'technical_quality', op: 'lt', value: 0.3 }],
  },
  {
    id: 'approve_high',
    label: 'Approve high-quality images',
    description: 'Composite score above 70%',
    action: 'approve',
    conditions: [{ field: 'composite_score', op: 'gte', value: 0.7 }],
  },
  {
    id: 'flag_multi_face',
    label: 'Flag multi-face images',
    description: 'More than 1 face detected',
    action: 'flag',
    conditions: [{ field: 'face_count', op: 'gt', value: 1 }],
  },
  {
    id: 'tag_closeup',
    label: 'Tag close-up portraits',
    description: 'Shot type is close-up',
    action: 'tag',
    tag: 'closeup',
    conditions: [{ field: 'shot_type', op: 'eq', value: 'closeup' }],
  },
  {
    id: 'reject_no_face',
    label: 'Reject images with no faces',
    description: 'For single-subject portrait datasets',
    action: 'reject',
    conditions: [{ field: 'face_count', op: 'eq', value: 0 }],
  },
  {
    id: 'flag_uncaptioned',
    label: 'Flag uncaptioned images',
    description: 'Caption is missing',
    action: 'flag',
    conditions: [{ field: 'active_caption_id', op: 'is_null', value: null }],
  },
]

function actionCls(action: string) {
  return (
    {
      approve: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20',
      reject: 'text-red-400 bg-red-500/10 border-red-500/20',
      flag: 'text-amber-400 bg-amber-500/10 border-amber-500/20',
      tag: 'text-blue-400 bg-blue-500/10 border-blue-500/20',
    }[action] ?? 'text-zinc-400 bg-zinc-500/10 border-zinc-500/20'
  )
}

export function AutoSort() {
  const activeProject = useProjectStore((s) => s.activeProject)
  const [activeRules, setActiveRules] = useState<SortRule[]>([])
  const [previews, setPreviews] = useState<SortPreview[]>([])
  const [applied, setApplied] = useState(false)

  const previewMutation = useMutation({
    mutationFn: async () => {
      const results = await Promise.all(
        activeRules.map(async (rule) => {
          const r = await api.post('/api/search/smart_filter', {
            project_id: activeProject?.id,
            rules: rule.conditions,
            limit: 5,
          })
          return {
            rule_label: rule.label,
            matched_count: r.data.length,
            sample_filenames: r.data.slice(0, 3).map((a: any) => a.filename),
            action: rule.action,
          } satisfies SortPreview
        })
      )
      setPreviews(results)
      return results
    },
  })

  const applyMutation = useMutation({
    mutationFn: async () => {
      for (const rule of activeRules) {
        if (rule.action !== 'approve' && rule.action !== 'reject') continue
        const r = await api.post('/api/search/smart_filter', {
          project_id: activeProject?.id,
          rules: rule.conditions,
          limit: 1000,
        })
        const ids = r.data.map((a: any) => a.id)
        if (ids.length === 0) continue
        await api.post(`/api/projects/${activeProject?.id}/assets/bulk-action`, {
          asset_ids: ids,
          action: rule.action,
        })
      }
      setApplied(true)
    },
  })

  const addRule = (rule: SortRule) => {
    if (!activeRules.find((r) => r.id === rule.id)) {
      setActiveRules((prev) => [...prev, rule])
      setPreviews([])
      setApplied(false)
    }
  }

  const removeRule = (id: string) => {
    setActiveRules((prev) => prev.filter((r) => r.id !== id))
    setPreviews([])
    setApplied(false)
  }

  if (!activeProject) {
    return (
      <div className="flex items-center justify-center h-full text-zinc-500">
        No project selected
      </div>
    )
  }

  return (
    <div className="flex h-full bg-zinc-950">
      {/* Left: preset rule list */}
      <div className="w-72 border-r border-zinc-800 flex flex-col">
        <div className="p-4 border-b border-zinc-800">
          <h2 className="text-white text-sm font-semibold flex items-center gap-2">
            <Wand2 size={16} className="text-violet-400" />
            Auto-Sort Rules
          </h2>
          <p className="text-zinc-500 text-xs mt-1">Select rules to apply to your dataset</p>
        </div>
        <div className="flex-1 overflow-y-auto p-3 space-y-2">
          {PRESET_RULES.map((rule) => {
            const isActive = !!activeRules.find((r) => r.id === rule.id)
            return (
              <button
                key={rule.id}
                onClick={() => (isActive ? removeRule(rule.id) : addRule(rule))}
                className={`w-full text-left p-3 rounded-lg border transition-all ${
                  isActive
                    ? 'border-violet-500/50 bg-violet-500/10'
                    : 'border-zinc-800 bg-zinc-900 hover:border-zinc-700'
                }`}
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="text-white text-xs font-medium">{rule.label}</span>
                  {isActive ? (
                    <CheckCircle size={12} className="text-violet-400" />
                  ) : (
                    <Plus size={12} className="text-zinc-500" />
                  )}
                </div>
                <p className="text-zinc-500 text-xs">{rule.description}</p>
                <span
                  className={`inline-block mt-1.5 text-[10px] px-1.5 py-0.5 rounded border ${actionCls(rule.action)}`}
                >
                  {rule.action}
                </span>
              </button>
            )
          })}
        </div>
      </div>

      {/* Right: active rules + preview */}
      <div className="flex-1 flex flex-col">
        <div className="p-4 border-b border-zinc-800 flex items-center gap-3">
          <span className="text-zinc-400 text-sm">
            {activeRules.length} rule{activeRules.length !== 1 ? 's' : ''} active
          </span>
          <div className="ml-auto flex gap-2">
            <button
              onClick={() => previewMutation.mutate()}
              disabled={activeRules.length === 0 || previewMutation.isPending}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-zinc-800 text-zinc-300 hover:bg-zinc-700 rounded text-sm disabled:opacity-50"
            >
              {previewMutation.isPending ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <Eye size={14} />
              )}
              Preview
            </button>
            <button
              onClick={() => applyMutation.mutate()}
              disabled={activeRules.length === 0 || applyMutation.isPending || previews.length === 0}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-violet-600 text-white hover:bg-violet-500 rounded text-sm disabled:opacity-50"
            >
              {applyMutation.isPending ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <Play size={14} />
              )}
              Apply Rules
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {activeRules.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-zinc-600">
              <Tag size={40} className="mb-3" />
              <p className="text-zinc-500">Select rules from the left panel</p>
              <p className="text-xs mt-1">Preview matches before applying</p>
            </div>
          ) : (
            <>
              {applied && (
                <div className="p-3 bg-emerald-500/10 border border-emerald-500/20 rounded-lg text-emerald-400 text-sm flex items-center gap-2">
                  <CheckCircle size={16} />
                  Rules applied successfully
                </div>
              )}
              {activeRules.map((rule) => {
                const preview = previews.find((p) => p.rule_label === rule.label)
                return (
                  <div key={rule.id} className="bg-zinc-900 border border-zinc-800 rounded-xl p-4">
                    <div className="flex items-center justify-between mb-2">
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="text-white text-sm font-medium">{rule.label}</span>
                          <span
                            className={`text-[10px] px-1.5 py-0.5 rounded border ${actionCls(rule.action)}`}
                          >
                            {rule.action}
                          </span>
                        </div>
                        <p className="text-zinc-500 text-xs mt-0.5">{rule.description}</p>
                      </div>
                      <button
                        onClick={() => removeRule(rule.id)}
                        className="text-zinc-600 hover:text-red-400"
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                    {preview && (
                      <div className="mt-3 p-2.5 bg-zinc-800/50 rounded-lg">
                        <div className="text-xs text-zinc-300 font-medium mb-1">
                          {preview.matched_count} images matched
                        </div>
                        {preview.sample_filenames.length > 0 && (
                          <div className="text-xs text-zinc-500">
                            e.g. {preview.sample_filenames.join(', ')}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )
              })}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
