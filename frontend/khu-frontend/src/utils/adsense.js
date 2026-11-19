// Google AdSense loader. Does NOTHING unless REACT_APP_ADSENSE_ID is set at build
// time (Vercel -> Environment Variables) AND the visitor accepted cookies
// (see consent.js). The Publisher ID is public (it is printed in ads.txt).
const ADS_ID_PATTERN = /^ca-pub-\d{10,20}$/;

export function adsConfigured(id = process.env.REACT_APP_ADSENSE_ID) {
  return ADS_ID_PATTERN.test(id || "");
}

export function initAds(id = process.env.REACT_APP_ADSENSE_ID, win = typeof window !== "undefined" ? window : null, doc = typeof document !== "undefined" ? document : null) {
  try {
    if (!win || !doc || !adsConfigured(id) || win.__khuAdsLoaded) return false;
    win.adsbygoogle = win.adsbygoogle || [];
    const s = doc.createElement("script");
    s.async = true;
    s.crossOrigin = "anonymous";
    s.src = "https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=" + encodeURIComponent(id);
    doc.head.appendChild(s);
    win.__khuAdsLoaded = true;
    return true;
  } catch (e) {
    return false; // ads must never break the app
  }
}
