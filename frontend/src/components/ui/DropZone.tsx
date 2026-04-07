import React, { useCallback, useEffect, useRef, useState } from 'react'
import { clsx } from 'clsx'
import { Upload } from 'lucide-react'
import {
  getRelativeImportPath,
  isSupportedIngestFile,
  toImportCandidate,
  type ImportFileCandidate,
} from '@/lib/importFiles'

interface DropZoneProps {
  onFiles: (files: ImportFileCandidate[]) => void
  className?: string
  children?: React.ReactNode
  disabled?: boolean
}

interface FileSystemEntry {
  isFile: boolean
  isDirectory: boolean
  fullPath: string
  name: string
}

interface FileSystemFileEntry extends FileSystemEntry {
  isFile: true
  file: (successCallback: (file: File) => void, errorCallback?: (error: DOMException) => void) => void
}

interface FileSystemDirectoryEntry extends FileSystemEntry {
  isDirectory: true
  createReader: () => {
    readEntries: (
      successCallback: (entries: FileSystemEntry[]) => void,
      errorCallback?: (error: DOMException) => void
    ) => void
  }
}

interface DataTransferItemWithEntry extends DataTransferItem {
  webkitGetAsEntry?: () => FileSystemEntry | null
}

async function readDirectoryEntries(
  entry: FileSystemDirectoryEntry
): Promise<FileSystemEntry[]> {
  const reader = entry.createReader()
  const entries: FileSystemEntry[] = []

  while (true) {
    const batch = await new Promise<FileSystemEntry[]>((resolve, reject) => {
      reader.readEntries(resolve, reject)
    })
    if (batch.length === 0) return entries
    entries.push(...batch)
  }
}

async function readDroppedEntry(entry: FileSystemEntry): Promise<ImportFileCandidate[]> {
  if (entry.isFile) {
    const file = await new Promise<File>((resolve, reject) => {
      ;(entry as FileSystemFileEntry).file(resolve, reject)
    })
    if (!isSupportedIngestFile(file)) return []
    return [toImportCandidate(file, entry.fullPath)]
  }

  if (entry.isDirectory) {
    const children = await readDirectoryEntries(entry as FileSystemDirectoryEntry)
    const nested = await Promise.all(children.map((child) => readDroppedEntry(child)))
    return nested.flat()
  }

  return []
}

export function DropZone({ onFiles, className, children, disabled }: DropZoneProps) {
  const [isDragOver, setIsDragOver] = useState(false)
  const folderInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!folderInputRef.current) return
    folderInputRef.current.setAttribute('webkitdirectory', '')
    folderInputRef.current.setAttribute('directory', '')
  }, [])

  const handleDrop = useCallback(
    async (e: React.DragEvent) => {
      e.preventDefault()
      setIsDragOver(false)
      if (disabled) return

      const dataTransferItems = Array.from(e.dataTransfer.items ?? []) as DataTransferItemWithEntry[]
      const entryResults = await Promise.all(
        dataTransferItems
          .map((item) => item.webkitGetAsEntry?.())
          .filter((entry): entry is FileSystemEntry => !!entry)
          .map((entry) => readDroppedEntry(entry))
      )
      const droppedCandidates = entryResults.flat()

      if (droppedCandidates.length > 0) {
        onFiles(droppedCandidates)
        return
      }

      const files = Array.from(e.dataTransfer.files)
        .filter((file) => isSupportedIngestFile(file))
        .map((file) => toImportCandidate(file))

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
      .filter((file) => isSupportedIngestFile(file))
      .map((file) => toImportCandidate(file, getRelativeImportPath(file)))
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
          <p className="text-text-secondary text-sm mt-1">Images and matching .txt sidecars supported</p>
        </div>
      )}

      {/* Hidden file input */}
      <input
        type="file"
        id="file-input-hidden"
        multiple
        accept="image/*,.txt"
        onChange={handleFileInput}
        className="hidden"
        disabled={disabled}
      />

      <input
        ref={folderInputRef}
        type="file"
        id="folder-input-hidden"
        multiple
        accept="image/*,.txt"
        onChange={handleFileInput}
        className="hidden"
        disabled={disabled}
      />
    </div>
  )
}
