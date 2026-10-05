/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react';
import { defineConfig, loadEnv } from 'vite';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  return {
    plugins: [react()],
    server: {
      host: '127.0.0.1',
      port: 5173,
      // The real backend is reached through /api in development.
      proxy: { '/api': { target: env.VITE_BACKEND_URL || 'http://localhost:8000', changeOrigin: true, rewrite: (p: string) => p.replace(/^\/api/, '') } },
    },
    test: {
      environment: 'jsdom',
      globals: true,
      setupFiles: ['./tests/setup.ts'],
      include: ['tests/unit/**/*.test.{ts,tsx}', 'tests/integration/**/*.test.{ts,tsx}'],
      css: false,
    },
  };
});
