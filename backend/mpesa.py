"""
mpesa.py — Safaricom Daraja "M-Pesa Express" (STK push) client.

Settings (environment, all secrets live on Render, never in git):
  MPESA_ENV              "sandbox" (default) or "production"
  MPESA_CONSUMER_KEY     from the Daraja app
  MPESA_CONSUMER_SECRET  from the Daraja app
  MPESA_SHORTCODE        paybill or till number that receives the money
  MPESA_PASSKEY          Lipa Na M-Pesa online passkey
  MPESA_TRANSACTION_TYPE "CustomerPayBillOnline" (default, paybill) or "CustomerBuyGoodsOnline" (till)
  MPESA_CALLBACK_SECRET  long random string; becomes part of the callback URL so only Safaricom's
                         copy of the URL (which we hand them) can report a payment
  PUBLIC_API_URL         this backend's public address, e.g. https://khu-backend.onrender.com
"""
import base64
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone

import requests

_TOKEN = {"value": "", "expires": 0.0}
_lock = threading.Lock()
TIMEOUT = 20


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def base_url() -> str:
    return "https://api.safaricom.co.ke" if _env("MPESA_ENV", "sandbox").lower() == "production" else "https://sandbox.safaricom.co.ke"


def configured() -> bool:
    return all(_env(k) for k in ("MPESA_CONSUMER_KEY", "MPESA_CONSUMER_SECRET", "MPESA_SHORTCODE", "MPESA_PASSKEY",
                                 "MPESA_CALLBACK_SECRET", "PUBLIC_API_URL"))


def callback_secret() -> str:
    return _env("MPESA_CALLBACK_SECRET")


def callback_url() -> str:
    return f"{_env('PUBLIC_API_URL').rstrip('/')}/api/shop/mpesa/callback/{callback_secret()}"


def normalize_phone(raw: str) -> str:
    """07XX / 01XX / +2547XX / 2547XX -> 2547XXXXXXXX (12 digits), or "" when it is not a Kenyan mobile."""
    d = re.sub(r"[^0-9]", "", raw or "")
    if d.startswith("0") and len(d) == 10:
        d = "254" + d[1:]
    elif len(d) == 9 and d[0] in "17":
        d = "254" + d
    return d if re.fullmatch(r"254[17][0-9]{8}", d) else ""


def _timestamp() -> str:
    return datetime.now(timezone(timedelta(hours=3))).strftime("%Y%m%d%H%M%S")


def _token() -> str:
    with _lock:
        if _TOKEN["value"] and time.time() < _TOKEN["expires"] - 30:
            return _TOKEN["value"]
        r = requests.get(f"{base_url()}/oauth/v1/generate?grant_type=client_credentials",
                         auth=(_env("MPESA_CONSUMER_KEY"), _env("MPESA_CONSUMER_SECRET")), timeout=TIMEOUT)
        r.raise_for_status()
        j = r.json()
        _TOKEN["value"] = j["access_token"]
        _TOKEN["expires"] = time.time() + int(j.get("expires_in", 3000))
        return _TOKEN["value"]


def _password(ts: str) -> str:
    return base64.b64encode(f"{_env('MPESA_SHORTCODE')}{_env('MPESA_PASSKEY')}{ts}".encode()).decode()


def stk_push(phone: str, amount: int, account_ref: str, description: str) -> dict:
    """Ask the customer's phone for the M-Pesa PIN. Returns {checkout_request_id, merchant_request_id}."""
    ts = _timestamp()
    body = {
        "BusinessShortCode": _env("MPESA_SHORTCODE"), "Password": _password(ts), "Timestamp": ts,
        "TransactionType": _env("MPESA_TRANSACTION_TYPE", "CustomerPayBillOnline"),
        "Amount": int(amount), "PartyA": phone, "PartyB": _env("MPESA_SHORTCODE"), "PhoneNumber": phone,
        "CallBackURL": callback_url(), "AccountReference": account_ref[:12], "TransactionDesc": description[:13] or "Order",
    }
    r = requests.post(f"{base_url()}/mpesa/stkpush/v1/processrequest", json=body,
                      headers={"Authorization": f"Bearer {_token()}"}, timeout=TIMEOUT)
    j = r.json() if r.content else {}
    if r.status_code != 200 or str(j.get("ResponseCode")) != "0":
        raise RuntimeError(str(j.get("errorMessage") or j.get("ResponseDescription") or f"M-Pesa error {r.status_code}")[:160])
    return {"checkout_request_id": j["CheckoutRequestID"], "merchant_request_id": j.get("MerchantRequestID", "")}


def stk_query(checkout_request_id: str) -> dict:
    """Ask Safaricom what happened to a payment request: {state: paid|failed|pending, receipt, amount, reason}."""
    ts = _timestamp()
    r = requests.post(f"{base_url()}/mpesa/stkpushquery/v1/query",
                      json={"BusinessShortCode": _env("MPESA_SHORTCODE"), "Password": _password(ts), "Timestamp": ts,
                            "CheckoutRequestID": checkout_request_id},
                      headers={"Authorization": f"Bearer {_token()}"}, timeout=TIMEOUT)
    j = r.json() if r.content else {}
    if "ResultCode" not in j:
        return {"state": "pending", "reason": str(j.get("errorMessage", ""))[:120]}  # still processing / not known yet
    code = str(j.get("ResultCode"))
    if code == "0":
        return {"state": "paid", "receipt": "", "amount": None, "reason": ""}
    return {"state": "failed", "reason": str(j.get("ResultDesc", "Payment was not completed"))[:160]}


def parse_callback(payload: dict):
    """Daraja callback body -> {checkout_request_id, ok, reason, receipt, amount, phone} or None if malformed."""
    try:
        cb = payload["Body"]["stkCallback"]
        out = {"checkout_request_id": str(cb["CheckoutRequestID"]), "ok": int(cb["ResultCode"]) == 0,
               "reason": str(cb.get("ResultDesc", ""))[:160], "receipt": "", "amount": None, "phone": ""}
        for it in (cb.get("CallbackMetadata") or {}).get("Item", []) or []:
            n, v = it.get("Name"), it.get("Value")
            if n == "MpesaReceiptNumber":
                out["receipt"] = str(v)[:30]
            elif n == "Amount":
                out["amount"] = float(v)
            elif n == "PhoneNumber":
                out["phone"] = str(v)
        return out
    except (KeyError, TypeError, ValueError):
        return None
