import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // Plain process.env doesn't see .env.local — Vite only loads that into
  // import.meta.env for client code by default. loadEnv reads the same
  // files for use here, in the Node-side config itself.
  const env = loadEnv(mode, process.cwd(), '')

  // VITE_BACKEND_PROXY_TARGET lets a single ngrok tunnel on the frontend
  // port cover the backend too — set it (see frontend/.env.local) and the
  // SPA's own API/WS calls go through this same origin, proxied straight to
  // the real Django server, instead of needing a second public tunnel
  // (ngrok's free tier only allows one simultaneous endpoint per account).
  // Unset in normal local dev, where the frontend already talks to
  // http://127.0.0.1:8000 directly — see api/http.ts's API_BASE_URL.
  const backendProxyTarget = env.VITE_BACKEND_PROXY_TARGET

  return {
    plugins: [react(), tailwindcss()],
    server: {
      port: 3000,
      strictPort: true,
      // Vite's own Host-header check, separate from Django's ALLOWED_HOSTS
      // — same ngrok-domain-demo reasoning as that setting.
      allowedHosts: ['.ngrok-free.app', '.ngrok-free.dev', '.ngrok.io', '.ngrok.app'],
      proxy: backendProxyTarget
        ? {
            '/api': { target: backendProxyTarget, changeOrigin: true },
            '/ws': { target: backendProxyTarget, changeOrigin: true, ws: true },
          }
        : undefined,
    },
  }
})
