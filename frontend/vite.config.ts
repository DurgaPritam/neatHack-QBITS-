import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The backend serves /api and the /r/{id} share pages; in dev, Vite forwards them.
const backend = process.env.VITE_BACKEND ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': backend,
      '/r': backend,
      '/badge': backend,
    },
  },
})
