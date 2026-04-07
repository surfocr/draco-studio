export interface ImportFileCandidate {
  file: File
  relativePath: string
}

const SUPPORTED_INGEST_EXTENSIONS = new Set([
  '.jpg',
  '.jpeg',
  '.png',
  '.webp',
  '.bmp',
  '.gif',
  '.tif',
  '.tiff',
  '.txt',
])

export function isSupportedIngestFile(file: Pick<File, 'name' | 'type'>): boolean {
  if (file.type?.startsWith('image/')) return true
  if (file.type === 'text/plain') return true

  const lastDot = file.name.lastIndexOf('.')
  const extension = lastDot >= 0 ? file.name.slice(lastDot).toLowerCase() : ''
  return SUPPORTED_INGEST_EXTENSIONS.has(extension)
}

export function getRelativeImportPath(file: File): string {
  const relativePath = (file as File & { webkitRelativePath?: string }).webkitRelativePath?.trim()
  return relativePath && relativePath.length > 0 ? relativePath : file.name
}

export function toImportCandidate(file: File, relativePath?: string): ImportFileCandidate {
  const normalized = (relativePath ?? getRelativeImportPath(file)).replaceAll('\\', '/').replace(/^\/+/, '')
  return {
    file,
    relativePath: normalized || file.name,
  }
}
