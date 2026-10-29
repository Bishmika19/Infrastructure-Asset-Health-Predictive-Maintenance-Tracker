import { configDefaults, defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

// Port and host are supplied by the manifest start command (--host/--port).
export default defineConfig({
  plugins: [react()],
  server: { host: '0.0.0.0', port: 3000, strictPort: true, allowedHosts: true },
  preview: { host: '0.0.0.0', port: 3000, strictPort: true, allowedHosts: true },
  test: {
    // Browser tests are executed only through `npm run test:a11y`.
    exclude: [...configDefaults.exclude, '**/*.spec.ts'],
  },
});
