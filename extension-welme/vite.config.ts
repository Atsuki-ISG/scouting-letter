import { defineConfig } from 'vite';
import { resolve } from 'path';

// WelMe 拡張の HTML ページをビルドする。content script / service worker
// は scripts/build.js が esbuild で別途バンドルする。
export default defineConfig({
  base: './',
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        sidepanel: resolve(__dirname, 'src/sidepanel/index.html'),
      },
    },
  },
});
