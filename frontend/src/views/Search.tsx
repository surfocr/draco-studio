import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Search as SearchIcon, Image, Type, Sliders, Loader2 } from 'lucide-react'
import { useProjectStore } from '@/stores/useProjectStore'
import { searchApi } from '@/hooks/useApi'

interface SearchResult {
  id: string
  filename: string
  thumbnail_url?: string
  composite_score?: number
  similarity?: number
  caption_text?: string
}

type SearchMode = 'text' | 'smart'

const SMART_FILTER_PRESETS = [
  { label: 'Low quality (<40%)', rules: [{ field: 'composite_score', op: 'lt', value: 0.4 }] },
  { label: 'No caption', rules: [{ field: 'active_caption_id', op: 'is_null', value: null }] },
  { label: 'Multi-face images', rules: [{ field: 'face_count', op: 'gt', value: 1 }] },
  { label: 'Close-up portraits', rules: [{ field: 'shot_type', op: 'eq', value: 'closeup' }] },
  { label: 'Not yet reviewed', rules: [{ field: 'review_state', op: 'eq', value: 'pending' }] },
  { label: 'Rejected images', rules: [{ field: 'review_state', op: 'eq', value: 'rejected' }] },
  { label: 'Augmented images', rules: [{ field: 'is_augmented', op: 'eq', value: true }] },
  { label: 'High aesthetic score', rules: [{ field: 'aesthetic_score', op: 'gte', value: 0.7 }] },
]

function SimilarityBar({ score }: { score: number }) {
  const pct = Math.round(score * 100)
  return (
    <div className="flex items-center gap-1.5">
      <div className="flex-1 h-1 bg-zinc-700 rounded-full overflow-hidden">
        <div
          className="h-full bg-violet-500 rounded-full"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-[10px] text-zinc-400 w-7 text-right">{pct}%</span>
    </div>
  )
}

export default function Search() {
  const activeProject = useProjectStore((s) => s.activeProject)
  const [mode, setMode] = useState<SearchMode>('text')
  const [textQuery, setTextQuery] = useState('')
  const [activePreset, setActivePreset] = useState<string | null>(null)

  const textSearch = useMutation({
    mutationFn: (query: string) =>
      searchApi.textSearch(activeProject!.id, query),
  })

  const smartFilter = useMutation({
    mutationFn: (rules: object[]) =>
      searchApi.smartFilter(activeProject!.id, rules),
  })

  const results: SearchResult[] = mode === 'text'
    ? (textSearch.data?.results || [])
    : (smartFilter.data || [])

  const isLoading = textSearch.isPending || smartFilter.isPending

  if (!activeProject) {
    return (
      <div className="flex items-center justify-center h-full text-zinc-500">
        No project selected
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full bg-zinc-950">
      {/* Header */}
      <div className="p-4 border-b border-zinc-800">
        <h1 className="text-lg font-semibold text-white flex items-center gap-2 mb-3">
          <SearchIcon size={20} className="text-violet-400" />
          Search & Smart Filters
        </h1>

        {/* Mode tabs */}
        <div className="flex gap-1 mb-3">
          {[
            { id: 'text' as SearchMode, label: 'Text Search', icon: Type },
            { id: 'smart' as SearchMode, label: 'Smart Filters', icon: Sliders },
          ].map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setMode(id)}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded text-sm font-medium transition-colors ${
                mode === id
                  ? 'bg-violet-600 text-white'
                  : 'bg-zinc-800 text-zinc-400 hover:bg-zinc-700 hover:text-zinc-200'
              }`}
            >
              <Icon size={14} />
              {label}
            </button>
          ))}
        </div>

        {/* Text search input */}
        {mode === 'text' && (
          <div className="flex gap-2">
            <div className="relative flex-1">
              <SearchIcon size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500" />
              <input
                value={textQuery}
                onChange={e => setTextQuery(e.target.value)}
                onKeyDown={e => {
                  if (e.key === 'Enter' && textQuery.trim()) {
                    textSearch.mutate(textQuery.trim())
                  }
                }}
                placeholder="e.g. 'woman smiling outdoors', 'close-up portrait with neutral expression'..."
                className="w-full bg-zinc-800 border border-zinc-700 rounded-lg pl-9 pr-4 py-2 text-sm text-white placeholder:text-zinc-500 focus:outline-none focus:border-violet-500"
              />
            </div>
            <button
              onClick={() => textQuery.trim() && textSearch.mutate(textQuery.trim())}
              disabled={!textQuery.trim() || isLoading}
              className="px-4 py-2 bg-violet-600 text-white rounded-lg text-sm font-medium hover:bg-violet-500 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
            >
              {isLoading ? <Loader2 size={14} className="animate-spin" /> : <SearchIcon size={14} />}
              Search
            </button>
          </div>
        )}

        {/* Smart filter presets */}
        {mode === 'smart' && (
          <div className="flex flex-wrap gap-2">
            {SMART_FILTER_PRESETS.map(preset => (
              <button
                key={preset.label}
                onClick={() => {
                  setActivePreset(preset.label)
                  smartFilter.mutate(preset.rules)
                }}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                  activePreset === preset.label
                    ? 'bg-violet-600 text-white'
                    : 'bg-zinc-800 text-zinc-300 hover:bg-zinc-700 border border-zinc-700'
                }`}
              >
                {preset.label}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Results */}
      <div className="flex-1 overflow-y-auto p-4">
        {isLoading && (
          <div className="flex items-center justify-center py-16 gap-3 text-zinc-400">
            <Loader2 size={20} className="animate-spin text-violet-400" />
            Searching...
          </div>
        )}

        {!isLoading && results.length === 0 && (mode === 'text' ? textSearch.isSuccess : smartFilter.isSuccess) && (
          <div className="flex flex-col items-center justify-center py-16 text-zinc-500">
            <SearchIcon size={32} className="mb-3 text-zinc-600" />
            <p>No results found</p>
            {mode === 'text' && <p className="text-xs mt-1">Try a different query or embed your images first</p>}
          </div>
        )}

        {!isLoading && results.length > 0 && (
          <>
            <div className="text-zinc-400 text-sm mb-3">
              {results.length} result{results.length !== 1 ? 's' : ''}
              {mode === 'text' && textSearch.data?.query && (
                <span className="text-zinc-500"> for "{textSearch.data.query}"</span>
              )}
            </div>
            <div className="grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-2">
              {results.map(result => (
                <div key={result.id} className="rounded-lg overflow-hidden border border-zinc-800 hover:border-zinc-600 transition-colors group">
                  <div className="aspect-square bg-zinc-800 relative">
                    {result.thumbnail_url ? (
                      <img
                        src={result.thumbnail_url}
                        alt={result.filename}
                        className="w-full h-full object-cover"
                        loading="lazy"
                      />
                    ) : (
                      <div className="w-full h-full flex items-center justify-center">
                        <Image size={24} className="text-zinc-600" />
                      </div>
                    )}
                    {result.composite_score != null && (
                      <div className="absolute top-1 right-1">
                        <span className={`text-[10px] font-mono px-1 py-0.5 rounded border ${
                          result.composite_score > 0.7
                            ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30'
                            : result.composite_score > 0.4
                            ? 'bg-amber-500/20 text-amber-400 border-amber-500/30'
                            : 'bg-red-500/20 text-red-400 border-red-500/30'
                        }`}>
                          {Math.round(result.composite_score * 100)}
                        </span>
                      </div>
                    )}
                  </div>
                  <div className="px-1.5 py-1.5 bg-zinc-900">
                    <p className="text-white text-[10px] truncate mb-0.5">{result.filename}</p>
                    {result.similarity != null && (
                      <SimilarityBar score={result.similarity} />
                    )}
                  </div>
                </div>
              ))}
            </div>
          </>
        )}

        {!isLoading && results.length === 0 && !textSearch.isSuccess && !smartFilter.isSuccess && (
          <div className="flex flex-col items-center justify-center py-16 text-zinc-600">
            <SearchIcon size={48} className="mb-4" />
            {mode === 'text' ? (
              <div className="text-center">
                <p className="text-lg font-medium text-zinc-500">Search by natural language</p>
                <p className="text-sm mt-2">Find images matching descriptions like<br />"confident pose", "plain white background", "looking away"</p>
                <p className="text-xs mt-3 text-zinc-600">Requires images to have been embedded first</p>
              </div>
            ) : (
              <div className="text-center">
                <p className="text-lg font-medium text-zinc-500">Filter your dataset by rules</p>
                <p className="text-sm mt-2">Select a preset above or build custom filters</p>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
