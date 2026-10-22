import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const backend = process.env.VITE_BACKEND ?? 'http://localhost:8000'

export default defineConfig({
  base: process.env.VITE_BASE ?? '/',  // CI đặt VITE_BASE=/booking/ để chạy dưới http://localhost/booking
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': backend,
      '/ws': { target: backend.replace(/^http/, 'ws'), ws: true },
    },
  },
})
