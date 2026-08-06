import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // `npm run dev` talks to a backend started with TIMEME_COOKIE_SECURE=false.
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
  build: { outDir: 'dist', sourcemap: false },
})
