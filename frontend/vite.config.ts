import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  server: {
    strictPort: true,
    proxy: {
      '/v1': {
        target: process.env.API_PROXY_TARGET ?? 'http://127.0.0.1:8000',
      },
      '/health': {
        target: process.env.API_PROXY_TARGET ?? 'http://127.0.0.1:8000',
      },
    },
  },
  test: { environment: 'jsdom', setupFiles: ['./src/test-setup.ts'] },
});
