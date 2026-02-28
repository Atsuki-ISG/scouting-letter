import { defineConfig } from 'vite';
import { resolve } from 'path';

// HTML pages only (sidepanel + popup)
// Content script and service worker are built separately by scripts/build.js
export default defineConfig({
  base: './',
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        sidepanel: resolve(__dirname, 'src/sidepanel/index.html'),
        popup: resolve(__dirname, 'src/popup/index.html'),
      },
    },
  },
});
