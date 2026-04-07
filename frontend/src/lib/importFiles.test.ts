import { describe, expect, it } from 'vitest'
import { getRelativeImportPath, isSupportedIngestFile, toImportCandidate } from './importFiles'

describe('importFiles helpers', () => {
  it('accepts image mime types and common extensions', () => {
    expect(isSupportedIngestFile({ name: 'sample.png', type: 'image/png' })).toBe(true)
    expect(isSupportedIngestFile({ name: 'sample.JPEG', type: '' })).toBe(true)
    expect(isSupportedIngestFile({ name: 'caption.txt', type: 'text/plain' })).toBe(true)
    expect(isSupportedIngestFile({ name: 'notes.csv', type: 'text/csv' })).toBe(false)
  })

  it('prefers webkitRelativePath when available', () => {
    const file = new File(['x'], 'face.png', { type: 'image/png' }) as File & {
      webkitRelativePath?: string
    }
    file.webkitRelativePath = 'dataset/subject/face.png'

    expect(getRelativeImportPath(file)).toBe('dataset/subject/face.png')
  })

  it('normalizes import candidate paths for upload', () => {
    const file = new File(['x'], 'face.png', { type: 'image/png' })
    expect(toImportCandidate(file, '\\dataset\\subject\\face.png').relativePath).toBe('dataset/subject/face.png')
  })
})
