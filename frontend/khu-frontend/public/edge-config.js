// Settings for the Cloudflare edge layer (see docs/EDGE_SETUP.md). Safe to publish: nothing here is secret.
// Leave both empty to keep calling the API directly with no human check.
window.KHU_EDGE = {
  apiBase: "",            // e.g. "https://khu-edge.YOURNAME.workers.dev" once the Worker is live
  turnstileSiteKey: ""    // the Turnstile *site key* (public). The secret key goes in the Worker, never here.
};
