# Monitoring: get a message when the scraper stalls

The app serves its last good data when KHU's site is slow or blocking, so fans see nothing wrong while the data quietly goes stale. A free outside monitor tells **you**.

## The address to watch

```
https://khu-backend.onrender.com/api/health?strict=1
```

- Normal call (`/api/health`): always answers 200 with details, for humans.
- With `?strict=1`: answers **200** when healthy and **503** when something is wrong, with a plain-English `problems` list. It is 503 when:
  - the circuit breaker is open (scraping paused after repeated failures), or
  - the last successful refresh from KHU is older than 45 minutes (`KHU_HEALTH_MAX_AGE_MINUTES`; never less than two refresh cycles), or
  - no refresh has succeeded an hour after the server started. (For 10 minutes after a restart it stays 200, so a deploy never raises a false alarm.)

Use the Render address directly. It stays open even when `EDGE_KEY` locks the API to the Worker.

## Set it up (UptimeRobot, free, about 3 minutes)

1. Create a free account at uptimerobot.com and turn on its alert e-mail (and the mobile app notifications if you like).
2. **Add New Monitor** → type **HTTP(s)** → friendly name `KHU backend` → URL as above → interval **5 minutes**.
3. Add yourself as the alert contact. UptimeRobot treats any 4xx/5xx answer as "down", which is exactly the 503.
4. Optional second monitor on the frontend address (`https://khu-live-app.vercel.app`) to catch Vercel problems.

Other monitors (Better Stack, Cronitor, a Cloudflare health check) work the same way: alert when the status is not 200.

## When it alerts

1. Open `https://khu-backend.onrender.com/api/health?strict=1` and read `problems`.
2. **Circuit breaker open:** KHU is down or blocking the server. It retries by itself every 5 minutes. Check kenyahockeyunion.org in a browser. If it loads fine for you, look in the Render log for "challenge" or "blocked" lines.
3. **Refresh too old with the breaker closed:** open the Render log and look for errors after the last "Refresh complete" line. Restarting the service (Render → Manual Deploy → Clear cache and deploy, or Restart) is safe.
4. **Not enough data yet after a restart:** wait a few minutes and check again.

Manual results and match corrections keep working while the scraper is stalled, so you can keep tables correct from the admin page in the meantime.
