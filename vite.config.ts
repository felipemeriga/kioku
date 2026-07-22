import { defineConfig } from 'vite'
import { homedir } from 'node:os'
import { join } from 'node:path'

export default defineConfig({
  server: {
    fs: {
      allow: [
        join(homedir(), '.npm'),
        join(homedir(), '.npm/_npx'),
      ],
    },
  },
})
