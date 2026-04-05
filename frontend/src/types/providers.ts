// Provider-related types

export type ProviderType =
  | 'caption'
  | 'face_detection'
  | 'embedding'
  | 'quality'
  | 'storage'
  | 'export'
  | 'ranking'

export interface ProviderInfo {
  id: string
  display_name: string
  provider_type: ProviderType
  is_available: boolean
  requires_gpu: boolean
}

export interface OllamaModel {
  name: string
  modified_at: string
  size: number
}
