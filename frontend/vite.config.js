
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'https://inforvex-backend.onrender.com',
        changeOrigin: true,
      },
      '/health': {
        target: 'https://inforvex-backend.onrender.com',
        changeOrigin: true,
      },
    },
  },
})
