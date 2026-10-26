import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react-swc';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  test: { environment: 'jsdom', setupFiles: './src/test/setup.js' },
  build: { rollupOptions: { output: { manualChunks: { charts: ['chart.js', 'react-chartjs-2'] } } } },
  server: {
    // This is the target URL for the proxy.
    // This is used to proxy the requests to the backend during development.
    // export VITE_PROXY_TARGET=http://localhost:5000 before running npm run dev
    proxy: {
      '/api': {
        target: process.env.VITE_PROXY_TARGET || 'http://localhost:5000',
        changeOrigin: true,
        secure: false,
        timeout: 300000,
        proxyTimeout: 290000
      },
      '/tv_shows': {
        target: process.env.VITE_PROXY_TARGET || 'http://localhost:5000',
        changeOrigin: true,
        secure: false,
      },
      '/movies': {
        target: process.env.VITE_PROXY_TARGET || 'http://localhost:5000',
        changeOrigin: true,
        secure: false,
      }
    },
  }
});