import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig(({ mode }) => {
  const envFromFile = loadEnv(mode, process.cwd(), '')
  // Prefer the OS-level env var (set by the launcher for dynamic port fallback),
  // then fall back to the .env file value, then to the default.
  const apiUrl =
    process.env.VITE_API_URL ||
    envFromFile.VITE_API_URL ||
    'http://127.0.0.1:18082'
  const wsUrl = apiUrl.replace(/^https?/, 'ws')

  return {
    plugins: [react()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },
    server: {
      port: 5173,
      proxy: {
        '/api': {
          target: apiUrl,
          changeOrigin: true,
        },
        '/ws': {
          target: wsUrl,
          ws: true,
        },
        '/files': {
          target: apiUrl,
          changeOrigin: true,
        },
      },
    },
    build: {
      outDir: 'dist',
      sourcemap: true,
    },
  }
})
