// Cloudflare Turnstile helper shared by the admin and agent pages. No site key set = does nothing.
window.khuTurnstile = function (box) {
  var cfg = window.KHU_EDGE || {};
  var state = { token: "", id: null };
  if (!cfg.turnstileSiteKey || !box) return { token: function () { return ""; }, reset: function () {}, on: false };
  function draw() {
    if (!window.turnstile || state.id !== null) return;
    state.id = window.turnstile.render(box, {
      sitekey: cfg.turnstileSiteKey,
      callback: function (t) { state.token = t; },
      "expired-callback": function () { state.token = ""; },
      "error-callback": function () { state.token = ""; }
    });
  }
  window.__khuTsReady = draw;
  var s = document.createElement("script");
  s.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit&onload=__khuTsReady";
  s.async = true; s.defer = true;
  document.head.appendChild(s);
  return {
    on: true,
    token: function () { return state.token; },
    reset: function () { state.token = ""; if (window.turnstile && state.id !== null) window.turnstile.reset(state.id); }
  };
};
