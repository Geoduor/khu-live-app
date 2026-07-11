import { useState, useEffect, useCallback } from "react";
import api from "../api";

/**
 * usePushNotifications — handles the full Web Push subscribe flow:
 *   1. Fetch the VAPID public key from our backend
 *   2. Ask the browser for notification permission
 *   3. Subscribe via the service worker's PushManager
 *   4. Send the subscription to our backend to store
 *
 * This is the same flow used by any real PWA (Twitter/X, Instagram web,
 * FotMob web) — no native app store needed for push to work.
 */

function urlBase64ToUint8Array(base64String) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = window.atob(base64);
  const outputArray = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; ++i) {
    outputArray[i] = rawData.charCodeAt(i);
  }
  return outputArray;
}

export function usePushNotifications() {
  const [permission, setPermission] = useState(
    typeof Notification !== "undefined" ? Notification.permission : "unsupported"
  );
  const [isSubscribed, setIsSubscribed] = useState(false);
  const [loading, setLoading] = useState(false);
  const [supported] = useState(
    "serviceWorker" in navigator && "PushManager" in window && typeof Notification !== "undefined"
  );

  // ── Check existing subscription on mount ──
  useEffect(() => {
    if (!supported) return;
    navigator.serviceWorker.ready.then((reg) => {
      reg.pushManager.getSubscription().then((sub) => {
        setIsSubscribed(!!sub);
      });
    });
  }, [supported]);

  const subscribe = useCallback(async (favoriteTeamUrls) => {
    if (!supported) return { success: false, reason: "Push notifications not supported in this browser" };

    setLoading(true);
    try {
      const perm = await Notification.requestPermission();
      setPermission(perm);
      if (perm !== "granted") {
        setLoading(false);
        return { success: false, reason: "Permission denied" };
      }

      const { data } = await api.get("/api/push/vapid-public-key");
      const applicationServerKey = urlBase64ToUint8Array(data.publicKey);

      const reg = await navigator.serviceWorker.ready;
      const subscription = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey,
      });

      // If the user already had favorites picked (e.g. from onboarding or
      // starring teams before ever enabling push), seed them immediately
      // so their very first notification is already correctly scoped —
      // rather than being global until the next favorites change.
      await api.post("/api/push/subscribe", {
        ...subscription.toJSON(),
        favoriteTeams: favoriteTeamUrls || [],
      });

      setIsSubscribed(true);
      setLoading(false);
      return { success: true };
    } catch (err) {
      console.error("Push subscribe failed:", err);
      setLoading(false);
      return { success: false, reason: err.message };
    }
  }, [supported]);

  const unsubscribe = useCallback(async () => {
    setLoading(true);
    try {
      const reg = await navigator.serviceWorker.ready;
      const subscription = await reg.pushManager.getSubscription();
      if (subscription) {
        await api.post("/api/push/unsubscribe", { endpoint: subscription.endpoint });
        await subscription.unsubscribe();
      }
      setIsSubscribed(false);
    } catch (err) {
      console.error("Push unsubscribe failed:", err);
    }
    setLoading(false);
  }, []);

  return { supported, permission, isSubscribed, loading, subscribe, unsubscribe };
}
