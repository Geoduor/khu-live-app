# Shop setup: take real M-Pesa payments

The shop is built but stays dormant ("Ordering opens soon") until you add M-Pesa settings. The Shop button only appears in the app once you have added a store.

## 1. Business questions to settle first (not code)

- **Who receives the money?** All payments land in the one paybill/till whose shortcode you set below. You then pay each store its share. The admin *Shop* tab shows what each store is owed and which cancelled orders need refunds. Keep a written agreement with every store (commission, payout dates, who handles returns and faulty goods).
- **Register the business** and get a Safaricom paybill or till in its name. Daraja production access needs this. Talk to an accountant about KRA obligations (income, VAT where it applies).
- **Consumer rules:** state the refund/return policy in the store note, and honour refunds for cancelled orders promptly. Stores must say what they deliver and the delivery time.
- **Data Protection Act:** orders hold customers' name, phone and address. The privacy page already covers this; consider registering with the Office of the Data Protection Commissioner and delete old orders when no longer needed.
- **Independence:** the app is an unofficial fan app. The shop says stores are independent sellers and not the Kenya Hockey Union. Do not use the KHU name or crest on store products.

## 2. Get Daraja credentials (sandbox first)

1. Create an account at developer.safaricom.co.ke and add an app with **Lipa Na M-Pesa Sandbox**.
2. Copy its **Consumer Key** and **Consumer Secret**. The sandbox shortcode is `174379`; the sandbox passkey is shown on the *Test credentials* page.

## 3. Add settings on Render (Environment tab)

| Name | Value |
|---|---|
| `MPESA_ENV` | `sandbox` (later `production`) |
| `MPESA_CONSUMER_KEY` / `MPESA_CONSUMER_SECRET` | from Daraja |
| `MPESA_SHORTCODE` | `174379` in sandbox; production: your paybill, or for a till the *store/head-office number* Safaricom gives you at Go Live |
| `MPESA_PARTY_B` | **Tills only:** your till number. Leave out for a paybill |
| `MPESA_PASSKEY` | from Daraja |
| `MPESA_TRANSACTION_TYPE` | `CustomerPayBillOnline` for a paybill; `CustomerBuyGoodsOnline` for a till |
| `MPESA_CALLBACK_SECRET` | a long random string you invent (30+ characters). Keep it private |
| `PUBLIC_API_URL` | `https://khu-backend.onrender.com` |

Never paste these secrets in chat or commit them. Save, and Render redeploys. The admin *Shop* tab then says "M-Pesa is switched on (sandbox)".

## 4. Add stores and products

Admin page → **Shop**: create a store (logo, tagline, delivery fee, WhatsApp), then add products (brand, type, price in KES, stock, up to 4 pictures). Reload the app: the Shop button appears.

## 5. Test in sandbox

Place an order from a phone with a Safaricom number. In sandbox the prompt is simulated by Safaricom's test tools, so use the Daraja simulator with the test number. Check that the order goes to *Paid, to prepare*, that cancelling flags a refund, and that stock goes down and back up.

## 6. Go live

1. Apply for **Go Live** on Daraja with your paybill/till; they give production keys and passkey.
2. Set `MPESA_ENV=production` and the production values above, then place a small real order (and refund it yourself).
3. If a payment is made but the callback is lost, the app re-checks with Safaricom when the customer reopens the order; the order never stays stuck.

## Day to day

- **Orders** list shows what to pack and where to deliver. Use *Preparing → Shipped → Delivered*.
- **Cancel + refund** returns the stock and adds a "refund due" note. Refunds are sent from your M-Pesa portal by you (the app does not move money out).
- **Settlement** per store is on the Shop tab; pay stores from the paybill/till on your agreed schedule.
- Orders are included in the nightly backup (they contain personal data: protect the bucket).
