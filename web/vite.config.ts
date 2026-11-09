import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const apiTarget = process.env.CK_API_TARGET || 'http://127.0.0.1:8765'

export default defineConfig({
  plugins: [vue()],
  base: '/',
  build: {
    outDir: fileURLToPath(new URL('../src/web_ui/dist', import.meta.url)),
    emptyOutDir: true,
    assetsDir: 'assets',
  },
  server: {
    proxy: {
      '/api': { target: apiTarget, changeOrigin: true },
      '/roadmap': { target: apiTarget, changeOrigin: true },
    },
  },
})
