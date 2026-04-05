import React, { useCallback, useState } from 'react'
import { clsx } from 'clsx'
import { Upload, FolderOpen } from 'lucide-react'

interface DropZoneProps {
  onFiles: (files: File[]) => void
  className?: string
  children?: React.ReactNode
  disabled?: boolean
}

export function DropZone({ onFiles, className, children, disabled }: DropZoneProps) {
  const [isDragOver, setIsDragOver] = useState(false)

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      setIsDragOver(false)
      if (disabled) return

      const files = Array.from(e.dataTransfer.files).filter((f) =>
        f.type.startsWith('image/')
      )
      if (files.length > 0) onFiles(files)
    },
    [onFiles, disabled]
  )

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    if (!disabled) setIsDragOver(true)
  }

  const handleDragLeave = (e: React.DragEvent) => {
    if (!e.currentTarget.contains(e.relatedTarget as Node)) {
      setIsDragOver(false)
    }
  }

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? [])
    if (files.length > 0) onFiles(files)
    e.target.value = ''
  }

  return (
    <div
      onDrop={handleDrop}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      className={clsx(
        'relative',
        isDragOver && !disabled && 'drop-zone-active',
        className
      )}
    >
      {children}

      {/* Full-screen drop overlay */}
      {isDragOver && (
        <div className="absolute inset-0 z-50 flex flex-col items-center justify-center bg-accent/10 border-2 border-dashed border-accent rounded-lg pointer-events-none">
          <Upload size={40} className="text-accent mb-3" />
          <p className="text-accent text-lg font-semibold">Drop images to import</p>
          <p className="text-text-secondary text-sm mt-1">JPG, PNG, WEBP, BMP supported</p>
        </div>
      )}

      {/* Hidden file input */}
      <input
        type="file"
        id="file-input-hidden"
        multiple
        accept="image/*"
        onChange={handleFileInput}
        className="hidden"
        disabled={disabled}
      />
    </div>
  )
}
