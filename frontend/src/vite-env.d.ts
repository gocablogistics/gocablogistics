/// <reference types="vite/client" />

interface ImportMetaEnv {
  // Overrides the default http://127.0.0.1:8000/api/v1 — set this in a
  // gitignored frontend/.env.local when tunneling the backend through
  // ngrok (or similar) for a client demo, so the browser talks to the
  // public backend URL instead of the developer's own localhost.
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
