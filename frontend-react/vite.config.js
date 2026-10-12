import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // '/api': 'http://127.0.0.1:8000',
      "/api/translate": { target: "http://127.0.0.1:8001", changeOrigin: true },  // FastAPI translator
       "/api/":{ target: "http://127.0.0.1:8000", changeOrigin: true },  // Django
    },
  },
})
