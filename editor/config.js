/* Deploy-time configuration. This file is intentionally not a module so it
   can be swapped per environment without touching the app code. */
window.MEMOBOOK = {
  // Base URL of the backend API, no trailing slash. Empty string = same
  // origin (the dev server serves the editor at /editor from the API host).
  // Can be overridden at runtime with ?api=https://… (persisted per browser).
  apiBase: '',

  // Dev only: pre-fill the simulated-payment signature so the "simulate
  // payment" button works without prompting. NEVER set in production.
  devPaymentSecret: ''
};
