import React, { useCallback, useEffect, useRef, useState } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import type { AssetSummary } from '@/types/api'
import { ImageCard } from './ImageCard'
import { getColumnCount, getItemHeight } from '@/hooks/useVirtualGrid'

interface VirtualGridProps {
  assets: AssetSummary[]
  selectedIds: Set<string>
  zoom: 0 | 1 | 2
  onSelect: (id: string, multi: boolean, range: boolean) => void
  onApprove?: (id: string) => void
  onReject?: (id: string) => void
  onFlag?: (id: string) => void
  lastSelectedIndex?: number
}

export function VirtualGrid({
  assets,
  selectedIds,
  zoom,
  onSelect,
  onApprove,
  onReject,
  onFlag,
}: VirtualGridProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [containerWidth, setContainerWidth] = useState(800)

  const GAP = 8

  // Observe container width
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const ro = new ResizeObserver(([entry]) => {
      setContainerWidth(entry.contentRect.width)
    })
    ro.observe(el)
    setContainerWidth(el.clientWidth)
    return () => ro.disconnect()
  }, [])

  const colCount = getColumnCount(zoom, containerWidth)
  const itemH = getItemHeight(zoom)
  const itemW = Math.floor((containerWidth - GAP * (colCount - 1)) / colCount)
  const rowCount = Math.ceil(assets.length / colCount)

  const virtualizer = useVirtualizer({
    count: rowCount,
    getScrollElement: () => containerRef.current,
    estimateSize: () => itemH + GAP,
    overscan: 4,
  })

  const handleSelect = useCallback(
    (id: string, multi: boolean, range: boolean) => {
      onSelect(id, multi, range)
    },
    [onSelect]
  )

  if (assets.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-text-secondary gap-3">
        <div className="text-5xl opacity-20">🖼</div>
        <p className="text-sm">No images match the current filters</p>
      </div>
    )
  }

  return (
    <div
      ref={containerRef}
      className="gallery-scroll overflow-y-auto h-full w-full"
      style={{ padding: GAP }}
    >
      <div
        style={{
          height: virtualizer.getTotalSize(),
          width: '100%',
          position: 'relative',
        }}
      >
        {virtualizer.getVirtualItems().map((virtualRow) => {
          const rowStart = virtualRow.index * colCount
          const cells = []

          for (let col = 0; col < colCount; col++) {
            const index = rowStart + col
            if (index >= assets.length) break
            const asset = assets[index]

            cells.push(
              <ImageCard
                key={asset.id}
                asset={asset}
                isSelected={selectedIds.has(asset.id)}
                width={itemW}
                height={itemH}
                onSelect={handleSelect}
                onApprove={onApprove}
                onReject={onReject}
                onFlag={onFlag}
                style={{
                  position: 'absolute',
                  top: virtualRow.start,
                  left: col * (itemW + GAP),
                }}
              />
            )
          }
          return cells
        })}
      </div>
    </div>
  )
}
