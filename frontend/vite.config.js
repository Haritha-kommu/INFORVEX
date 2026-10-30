import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Proxy local API traffic through Vite. This avoids CORS failures when Vite
// chooses 5174 (or another available port) instead of the default 5173.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/health': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
