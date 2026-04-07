import { useCallback, useMemo } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'

interface UseVirtualGridOptions {
  itemCount: number
  containerHeight: number
  containerWidth: number
  columnCount: number
  itemHeight: number
  gap?: number
  overscan?: number
}

export function useVirtualGrid({
  itemCount,
  containerWidth,
  columnCount,
  itemHeight,
  gap = 8,
  overscan = 3,
}: UseVirtualGridOptions) {
  const rowCount = Math.ceil(itemCount / columnCount)
  const itemWidth = Math.floor((containerWidth - gap * (columnCount - 1)) / columnCount)

  const virtualizer = useVirtualizer({
    count: rowCount,
    getScrollElement: useCallback(() => document.querySelector('.gallery-scroll'), []),
    estimateSize: () => itemHeight + gap,
    overscan,
  })

  const virtualRows = virtualizer.getVirtualItems()

  // Expand rows back to individual items
  const virtualItems = useMemo(() => {
    const items: Array<{ index: number; rowIndex: number; colIndex: number; start: number }> = []
    for (const row of virtualRows) {
      for (let col = 0; col < columnCount; col++) {
        const index = row.index * columnCount + col
        if (index >= itemCount) break
        items.push({
          index,
          rowIndex: row.index,
          colIndex: col,
          start: row.start,
        })
      }
    }
    return items
  }, [virtualRows, columnCount, itemCount])

  return {
    virtualizer,
    virtualItems,
    totalHeight: virtualizer.getTotalSize(),
    itemWidth,
    itemHeight,
  }
}

/** Determine column count based on zoom level and container width. */
export function getColumnCount(zoom: 0 | 1 | 2, containerWidth: number): number {
  const baseWidths = [180, 240, 320] // small, medium, large thumbnail targets
  const targetWidth = baseWidths[zoom]
  return Math.max(1, Math.floor((containerWidth + 8) / (targetWidth + 8)))
}

/** Determine item height based on zoom level. */
export function getItemHeight(zoom: 0 | 1 | 2): number {
  return [180, 240, 320][zoom]
}
