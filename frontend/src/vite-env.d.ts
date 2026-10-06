/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL of the API, e.g. http://localhost:8000 (defaults to the deployed API). */
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
