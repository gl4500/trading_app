import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import fs from 'fs'
import path from 'path'

// Backend may be HTTPS (self-signed cert) — proxy handles the TLS internally.
// Vite itself serves plain HTTP so the browser never sees a cert warning.
const certsDir  = path.resolve(__dirname, '..', 'certs')
const certFile  = path.join(certsDir, 'cert.pem')
const hasCerts  = fs.existsSync(certFile)
const backendBase = hasCerts ? 'https://localhost:8000' : 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: '0.0.0.0',   // listen on all interfaces (required for Tailscale access)
    open: true,         // auto-open browser when Vite is ready
    https: hasCerts ? { key: fs.readFileSync(path.join(certsDir, 'key.pem')), cert: fs.readFileSync(certFile) } : false,
    proxy: {
      '/api': {
        target: backendBase,
        changeOrigin: true,
        secure: false,   // accept self-signed backend cert
      },
      '/ws': {
        target: backendBase,
        ws: true,
        changeOrigin: true,
        secure: false,
      },
    },
  },
})
