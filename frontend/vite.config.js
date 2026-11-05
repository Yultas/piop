import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [vue()],
  // vue-i18n feature flags; JIT compilation avoids new Function(), which the CSP (no unsafe-eval) blocks
  define: {
    __VUE_I18N_FULL_INSTALL__: true,
    __VUE_I18N_LEGACY_API__: false,
    __INTLIFY_PROD_DEVTOOLS__: false,
    __INTLIFY_JIT_COMPILATION__: true
  },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  server: {
    port: 3000,
    host: '0.0.0.0',
    proxy: {
      '/api': {
        target: process.env.VITE_BACKEND_URL || 'http://localhost:8080',
        changeOrigin: true,
        configure: (proxy) => {
          // Never trust a client-sent X-Real-IP: the backend rate-limits by it
          proxy.on('proxyReq', (proxyReq, req) => proxyReq.setHeader('X-Real-IP', req.socket.remoteAddress || ''))
        }
      }
    }
  }
})
