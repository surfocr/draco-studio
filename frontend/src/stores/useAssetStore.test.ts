import { beforeEach, describe, expect, it } from 'vitest'
import { useAssetStore } from './useAssetStore'
import type { AssetSummary } from '@/types/api'

function makeAsset(id: string, overrides: Partial<AssetSummary> = {}): AssetSummary {
  return {
    id,
    filename: `${id}.png`,
    width: 512,
    height: 512,
    composite_score: 0.8,
    face_count: 0,
    review_state: 'pending',
    is_flagged: false,
    is_rejected: false,
    is_augmented: false,
    shot_type: 'close_up',
    thumbnail_path: null,
    active_caption_id: null,
    duplicate_cluster_id: null,
    trueskill_mu: 25.0,
    imported_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

describe('useAssetStore', () => {
  beforeEach(() => {
    useAssetStore.setState({
      assets: [],
      total: 0,
      page: 1,
      pageSize: 50,
      hasNext: false,
      isLoading: false,
      selectedIds: new Set(),
      filters: {},
      sortBy: 'imported_at',
      sortDir: 'desc',
      zoom: 1,
    })
  })

  // ── setAssets / setLoading ─────────────────────────────────────────────────

  it('setAssets stores the list, total and hasNext', () => {
    const assets = [makeAsset('a'), makeAsset('b')]
    useAssetStore.getState().setAssets(assets, 10, true)

    const state = useAssetStore.getState()
    expect(state.assets).toHaveLength(2)
    expect(state.total).toBe(10)
    expect(state.hasNext).toBe(true)
    expect(state.isLoading).toBe(false)
  })

  it('setLoading sets the loading flag', () => {
    useAssetStore.getState().setLoading(true)
    expect(useAssetStore.getState().isLoading).toBe(true)

    useAssetStore.getState().setLoading(false)
    expect(useAssetStore.getState().isLoading).toBe(false)
  })

  // ── updateAsset ────────────────────────────────────────────────────────────

  it('updateAsset patches only the target asset', () => {
    useAssetStore.getState().setAssets([makeAsset('a'), makeAsset('b')], 2, false)
    useAssetStore.getState().updateAsset('a', { review_state: 'approved' })

    const state = useAssetStore.getState()
    expect(state.assets.find((x) => x.id === 'a')?.review_state).toBe('approved')
    expect(state.assets.find((x) => x.id === 'b')?.review_state).toBe('pending')
  })

  it('updateAsset ignores an id that does not exist', () => {
    useAssetStore.getState().setAssets([makeAsset('a')], 1, false)
    useAssetStore.getState().updateAsset('nonexistent', { review_state: 'rejected' })

    expect(useAssetStore.getState().assets).toHaveLength(1)
    expect(useAssetStore.getState().assets[0].review_state).toBe('pending')
  })

  // ── removeAsset ────────────────────────────────────────────────────────────

  it('removeAsset removes the asset from the list', () => {
    useAssetStore.getState().setAssets([makeAsset('a'), makeAsset('b'), makeAsset('c')], 3, false)
    useAssetStore.getState().removeAsset('b')

    const ids = useAssetStore.getState().assets.map((x) => x.id)
    expect(ids).toEqual(['a', 'c'])
  })

  it('removeAsset also removes the id from selectedIds', () => {
    useAssetStore.getState().setAssets([makeAsset('a'), makeAsset('b')], 2, false)
    useAssetStore.getState().setSelection(['a', 'b'])
    useAssetStore.getState().removeAsset('a')

    expect(useAssetStore.getState().selectedIds.has('a')).toBe(false)
    expect(useAssetStore.getState().selectedIds.has('b')).toBe(true)
  })

  // ── selection ──────────────────────────────────────────────────────────────

  it('toggleSelect adds an id that was not selected', () => {
    useAssetStore.getState().toggleSelect('x')
    expect(useAssetStore.getState().selectedIds.has('x')).toBe(true)
  })

  it('toggleSelect removes an id that was already selected', () => {
    useAssetStore.getState().setSelection(['x'])
    useAssetStore.getState().toggleSelect('x')
    expect(useAssetStore.getState().selectedIds.has('x')).toBe(false)
  })

  it('selectAll selects every loaded asset', () => {
    useAssetStore.getState().setAssets([makeAsset('a'), makeAsset('b'), makeAsset('c')], 3, false)
    useAssetStore.getState().selectAll()

    const selected = useAssetStore.getState().selectedIds
    expect(selected.size).toBe(3)
    expect(selected.has('a')).toBe(true)
    expect(selected.has('c')).toBe(true)
  })

  it('clearSelection empties the selected set', () => {
    useAssetStore.getState().setSelection(['a', 'b'])
    useAssetStore.getState().clearSelection()
    expect(useAssetStore.getState().selectedIds.size).toBe(0)
  })

  it('setSelection replaces the selection with the provided ids', () => {
    useAssetStore.getState().setSelection(['a', 'b'])
    useAssetStore.getState().setSelection(['c'])

    const selected = useAssetStore.getState().selectedIds
    expect(selected.has('a')).toBe(false)
    expect(selected.has('c')).toBe(true)
  })

  // ── filters ────────────────────────────────────────────────────────────────

  it('setFilter adds a filter and resets page to 1', () => {
    useAssetStore.setState({ page: 3 })
    useAssetStore.getState().setFilter('review_state', 'approved')

    expect(useAssetStore.getState().filters.review_state).toBe('approved')
    expect(useAssetStore.getState().page).toBe(1)
  })

  it('clearFilters resets all filters and page to 1', () => {
    useAssetStore.getState().setFilter('review_state', 'approved')
    useAssetStore.setState({ page: 4 })
    useAssetStore.getState().clearFilters()

    expect(useAssetStore.getState().filters).toEqual({})
    expect(useAssetStore.getState().page).toBe(1)
  })

  // ── sorting ────────────────────────────────────────────────────────────────

  it('setSortBy updates sortBy and resets page', () => {
    useAssetStore.setState({ page: 2 })
    useAssetStore.getState().setSortBy('composite_score')

    expect(useAssetStore.getState().sortBy).toBe('composite_score')
    expect(useAssetStore.getState().page).toBe(1)
  })

  it('setSortDir updates sortDir and resets page', () => {
    useAssetStore.setState({ page: 5 })
    useAssetStore.getState().setSortDir('asc')

    expect(useAssetStore.getState().sortDir).toBe('asc')
    expect(useAssetStore.getState().page).toBe(1)
  })

  it('toggleSort on a new field sets it to desc', () => {
    useAssetStore.setState({ sortBy: 'imported_at', sortDir: 'desc' })
    useAssetStore.getState().toggleSort('composite_score')

    expect(useAssetStore.getState().sortBy).toBe('composite_score')
    expect(useAssetStore.getState().sortDir).toBe('desc')
  })

  it('toggleSort on the current desc field flips to asc', () => {
    useAssetStore.setState({ sortBy: 'composite_score', sortDir: 'desc' })
    useAssetStore.getState().toggleSort('composite_score')

    expect(useAssetStore.getState().sortDir).toBe('asc')
  })

  it('toggleSort on the current asc field stays at desc', () => {
    useAssetStore.setState({ sortBy: 'composite_score', sortDir: 'asc' })
    useAssetStore.getState().toggleSort('composite_score')

    expect(useAssetStore.getState().sortDir).toBe('desc')
  })

  // ── zoom / page ────────────────────────────────────────────────────────────

  it('setZoom stores the zoom level', () => {
    useAssetStore.getState().setZoom(2)
    expect(useAssetStore.getState().zoom).toBe(2)

    useAssetStore.getState().setZoom(0)
    expect(useAssetStore.getState().zoom).toBe(0)
  })

  it('setPage updates the page number', () => {
    useAssetStore.getState().setPage(7)
    expect(useAssetStore.getState().page).toBe(7)
  })
})
