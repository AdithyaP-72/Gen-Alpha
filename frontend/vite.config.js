import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      // Backend port is configurable via API_PORT on the Flask side;
      // default 5001 (5000 collides with macOS AirPlay Receiver).
      '/api': {
        target: `http://localhost:${process.env.API_PORT || 5001}`,
        changeOrigin: true,
      },
    },
  },
})
