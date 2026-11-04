import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// pdfjs-dist 4 ships top-level await, so the build targets ES2022.
export default defineConfig({
  plugins: [react()],
  build: {
    target: 'es2022',
    sourcemap: false,
    chunkSizeWarningLimit: 1600,
  },
  optimizeDeps: {
    esbuildOptions: { target: 'es2022' },
  },
});
