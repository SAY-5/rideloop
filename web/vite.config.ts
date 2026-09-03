import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The dev server proxies each service so the browser talks to one origin.
const services = {
  '/api/location': 'http://localhost:8001',
  '/api/rides': 'http://localhost:8002',
  '/api/dispatch': 'http://localhost:8003',
}

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: Object.fromEntries(
      Object.entries(services).map(([prefix, target]) => [
        prefix,
        { target, rewrite: (path: string) => path.slice(prefix.length) },
      ]),
    ),
  },
})
