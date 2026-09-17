/// <reference types="vite/client" />

// No `ImportMetaEnv` of this project's own. The API base used to live here as
// `VITE_API_BASE`; ADR 0007 put the page and the API on one origin, so there is no host
// left to configure and `api.ts` calls relative paths. Re-adding a base URL here would
// reintroduce the second origin that decision exists to remove.
