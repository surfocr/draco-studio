import React, { useCallback, useEffect, useRef, useState } from 'react'
import { clsx } from 'clsx'
import { Check, X, Flag, AlertTriangle, Copy } from 'lucide-react'
import type { AssetSummary } from '@/types/api'
import { Score } from './Score'
import { assetsApi } from '@/hooks/useApi'

interface ImageCardProps {
  asset: AssetSummary
  isSelected: boolean
  width: number
  height: number
  onSelect: (id: string, multi: boolean, range: boolean) => void
  onApprove?: (id: string) => void
  onReject?: (id: string) => void
  onFlag?: (id: string) => void
  style?: React.CSSProperties
}

export const ImageCard = React.memo(function ImageCard({
  asset,
  isSelected,
  width,
  height,
  onSelect,
  onApprove,
  onReject,
  onFlag,
  style,
}: ImageCardProps) {
  const [isLoaded, setIsLoaded] = useState(false)
  const [loadFailed, setLoadFailed] = useState(false)
  const [isHovered, setIsHovered] = useState(false)
  const [imgSrc, setImgSrc] = useState('')
  const imgRef = useRef<HTMLImageElement>(null)

  const thumbUrl = assetsApi.thumbnailUrl(asset.id, 512)
  const originalUrl = assetsApi.originalUrl(asset.id)

  useEffect(() => {
    setImgSrc(thumbUrl)
    setIsLoaded(false)
    setLoadFailed(false)
  }, [thumbUrl])

  const handleClick = useCallback(
    (e: React.MouseEvent) => {
      onSelect(asset.id, e.ctrlKey || e.metaKey, e.shiftKey)
    },
    [asset.id, onSelect]
  )

  // Status badge
  const getStatusBadge = () => {
    if (asset.is_rejected) return { label: 'Rejected', color: 'var(--danger)' }
    if (asset.is_flagged) return { label: 'Flagged', color: 'var(--warning)' }
    if (asset.review_state === 'approved') return { label: 'Approved', color: 'var(--success)' }
    return null
  }
  const statusBadge = getStatusBadge()

  return (
    <div
      className={clsx('image-card group', {
        selected: isSelected,
        rejected: asset.is_rejected,
        flagged: asset.is_flagged && !asset.is_rejected,
      })}
      style={{ ...style, width, height }}
      onClick={handleClick}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      {/* Thumbnail */}
      {!isLoaded && (
        <div className="skeleton absolute inset-0" />
      )}
      <img
        ref={imgRef}
        src={imgSrc}
        alt={asset.filename}
        className={clsx(
          'w-full h-full object-cover transition-opacity',
          isLoaded ? 'opacity-100' : 'opacity-0'
        )}
        loading="lazy"
        onLoad={() => {
          setIsLoaded(true)
          setLoadFailed(false)
        }}
        onError={() => {
          if (imgSrc !== originalUrl) {
            setIsLoaded(false)
            setImgSrc(originalUrl)
            return
          }
          setLoadFailed(true)
        }}
        draggable={false}
      />

      {loadFailed && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-black/60 px-3 text-center text-white">
          <AlertTriangle size={20} className="text-yellow-300" />
          <p className="text-xs font-medium">Image preview unavailable</p>
        </div>
      )}

      {/* Selection checkbox */}
      {(isSelected || isHovered) && (
        <div
          className={clsx(
            'absolute top-2 left-2 w-5 h-5 rounded border-2 flex items-center justify-center',
            'transition-all',
            isSelected
              ? 'bg-accent border-accent'
              : 'bg-black/40 border-white/60 hover:border-white'
          )}
          onClick={(e) => {
            e.stopPropagation()
            onSelect(asset.id, true, false)
          }}
        >
          {isSelected && <Check size={12} className="text-white" />}
        </div>
      )}

      {/* Score badge */}
      <div className="score-badge">
        <Score value={asset.composite_score} size="sm" />
      </div>

      {/* Status badge */}
      {statusBadge && (
        <div
          className="absolute top-2 right-2 badge text-[10px]"
          style={{ background: `${statusBadge.color}22`, color: statusBadge.color }}
        >
          {statusBadge.label}
        </div>
      )}

      {/* Duplicate badge */}
      {asset.duplicate_cluster_id && (
        <div className="absolute top-2 right-2 badge badge-yellow text-[10px]" style={statusBadge ? { top: '2rem' } : undefined}>
          <Copy size={9} className="mr-1" />
          Dup
        </div>
      )}

      {/* Augmented badge */}
      {asset.is_augmented && (
        <div className="absolute bottom-2 left-2 badge badge-purple text-[10px]">AI</div>
      )}

      {/* Quick actions on hover */}
      {isHovered && !asset.is_rejected && (
        <div className="absolute bottom-2 right-2 flex gap-1">
          {onApprove && (
            <button
              className="w-6 h-6 rounded bg-green-600/80 hover:bg-green-500 flex items-center justify-center backdrop-blur-sm"
              onClick={(e) => {
                e.stopPropagation()
                onApprove(asset.id)
              }}
              title="Approve"
            >
              <Check size={12} className="text-white" />
            </button>
          )}
          {onFlag && (
            <button
              className="w-6 h-6 rounded bg-yellow-600/80 hover:bg-yellow-500 flex items-center justify-center backdrop-blur-sm"
              onClick={(e) => {
                e.stopPropagation()
                onFlag(asset.id)
              }}
              title="Flag"
            >
              <Flag size={12} className="text-white" />
            </button>
          )}
          {onReject && (
            <button
              className="w-6 h-6 rounded bg-red-600/80 hover:bg-red-500 flex items-center justify-center backdrop-blur-sm"
              onClick={(e) => {
                e.stopPropagation()
                onReject(asset.id)
              }}
              title="Reject"
            >
              <X size={12} className="text-white" />
            </button>
          )}
        </div>
      )}

      {/* Face count indicator */}
      {asset.face_count > 0 && (
        <div className="absolute top-8 left-2 w-4 h-4 rounded-full bg-black/60 text-white text-[9px] font-bold flex items-center justify-center">
          {asset.face_count}
        </div>
      )}
    </div>
  )
})
