import { useState, useEffect, useCallback } from "react";
import api from "../api";

const STORAGE_KEY = "khu_favorite_teams";
const ONBOARDING_SEEN_KEY = "khu_onboarding_seen";

/**
 * useFavorites — device-local favorite teams (Finding 4 from research).
 *
 * Deliberately NOT account-based: KHU's audience is casual fans checking
 * scores, not power users needing cross-device sync. Zero-friction
 * localStorage matches how regional sports apps (as opposed to global
 * giants like ESPN, who need accounts for other business reasons) ship this.
 *
 * Stored as { team_url: team_name } rather than just names, because the
 * backend scopes push notifications by team_url (the same value already
 * present on standings rows and match cards) — this lets a favorite
 * survive two clubs sharing a display name across different leagues,
 * and lets us sync straight to the push subscription without a lookup.
 */
export function useFavorites() {
  const [favorites, setFavorites] = useState(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      return stored ? JSON.parse(stored) : {};
    } catch {
      return {};
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(favorites));
    } catch {
      // localStorage unavailable (private browsing etc) — fail silently,
      // favorites just won't persist across reloads this session
    }
  }, [favorites]);

  // ── Push this device's current favorites list to its push subscription ──
  // (no-op if the user hasn't enabled notifications — that's fine, they
  // can still use favorites purely for the personalized home feed)
  const syncToPushSubscription = useCallback(async (teamUrls) => {
    if (!("serviceWorker" in navigator)) return;
    try {
      const reg = await navigator.serviceWorker.ready;
      const subscription = await reg.pushManager.getSubscription();
      if (subscription) {
        await api.post("/api/push/update-favorites", {
          endpoint: subscription.endpoint,
          favoriteTeams: teamUrls,
        });
      }
    } catch (e) {
      console.warn("Could not sync favorites to push subscription:", e);
    }
  }, []);

  const isFavorite = useCallback((teamUrl) => Boolean(favorites[teamUrl]), [favorites]);

  const toggleFavorite = useCallback((teamUrl, teamName) => {
    setFavorites((prev) => {
      const next = { ...prev };
      if (next[teamUrl]) {
        delete next[teamUrl];
      } else {
        next[teamUrl] = teamName || teamUrl;
      }
      syncToPushSubscription(Object.keys(next));
      return next;
    });
  }, [syncToPushSubscription]);

  const favoriteList = Object.entries(favorites).map(([team_url, team_name]) => ({ team_url, team_name }));

  return { favorites, favoriteList, isFavorite, toggleFavorite };
}

/**
 * useOnboarding — tracks whether the first-run "which teams do you follow?"
 * prompt has been shown (Finding 2 — passive stars alone under-deliver;
 * FotMob/TheScore/ESPN all show this prompt explicitly on first launch).
 */
export function useOnboarding() {
  const [hasSeenOnboarding, setHasSeenOnboarding] = useState(() => {
    try {
      return localStorage.getItem(ONBOARDING_SEEN_KEY) === "true";
    } catch {
      return true; // if storage is broken, don't force onboarding repeatedly
    }
  });

  const markOnboardingSeen = useCallback(() => {
    try {
      localStorage.setItem(ONBOARDING_SEEN_KEY, "true");
    } catch {
      // ignore
    }
    setHasSeenOnboarding(true);
  }, []);

  return { hasSeenOnboarding, markOnboardingSeen };
}
