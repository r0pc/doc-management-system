/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** True in `vite dev` and in the test runner; false in `vite build`. */
  readonly DEV: boolean;
  readonly PROD: boolean;
  readonly MODE: string;
  /**
   * Explicit opt-in for the hardcoded dev-persona switcher. It is OFF unless
   * this is a dev build; setting it to 'false' turns it off even in dev.
   * It can never be turned ON in a production build.
   */
  readonly VITE_DEV_PERSONAS?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
