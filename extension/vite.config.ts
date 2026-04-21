import { defineConfig } from 'vite';
import { resolve } from 'path';

// HTML pages only (sidepanel + popup)
// Content script and service worker are built separately by scripts/build.js
export default defineConfig({
  base: './',
  build: {
    outDir: 'scout_extension',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        sidepanel: resolve(__dirname, 'src/sidepanel/index.html'),
        'sidepanel-welme': resolve(__dirname, 'src/sidepanel/welme/index.html'),
        popup: resolve(__dirname, 'src/popup/index.html'),
      },
    },
  },
});
