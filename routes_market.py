# routes_market.py
import os, json, requests, math
from datetime import datetime, timedelta, timezone
from flask import Blueprint, request, jsonify

market_bp = Blueprint('market_bp', __name__)

DATA_GOV_API_KEY = os.getenv("DATA_GOV_API_KEY")
AGMARKNET_RESOURCE_ID = "9ef84268-d588-465a-a308-a864a43d0070"  # Agmarknet daily mandi prices
IST = timezone(timedelta(hours=5, minutes=30))

def ymd_to_ddmmyyyy(ymd):
    y, m, d = ymd.split("-")
    return f"{d}/{m}/{y}"

def fetch_records(filters, limit):
    url = f"https://api.data.gov.in/resource/{AGMARKNET_RESOURCE_ID}"
    params = {
        "api-key": DATA_GOV_API_KEY,
        "format": "json",
        "limit": limit,
        "filters": json.dumps(filters, ensure_ascii=False),
    }
    r = requests.get(url, params=params, timeout=12)
    r.raise_for_status()
    return r.json().get("records", [])

@market_bp.get("/api/market-prices")
def market_prices():
    if not DATA_GOV_API_KEY:
        return jsonify({"error": "DATA_GOV_API_KEY not set"}), 500

    commodity = (request.args.get("commodity") or "").strip()
    states_csv = (request.args.get("states") or "").strip()
    markets_csv = (request.args.get("markets") or "").strip()
    unit = (request.args.get("unit") or "quintal").lower()
    limit = max(1, min(500, int(request.args.get("limit", "100"))))
    date_ymd = (request.args.get("date") or "").strip()

    # pick date(s): exact if passed, otherwise today→yesterday→-2
    if date_ymd:
        dates_ddmmyyyy = [ymd_to_ddmmyyyy(date_ymd)]
    else:
        base = datetime.now(IST).date()
        dates_ddmmyyyy = [
            base.strftime("%d/%m/%Y"),
            (base - timedelta(days=1)).strftime("%d/%m/%Y"),
            (base - timedelta(days=2)).strftime("%d/%m/%Y"),
        ]

    states  = [s.strip() for s in states_csv.split(",") if s.strip()] or [None]
    markets = [m.strip() for m in markets_csv.split(",") if m.strip()]

    # fetch newest date that has data
    collected = []
    for dd in dates_ddmmyyyy:
        partial = []
        for st in states:
            base_filters = {"arrival_date": dd}
            if commodity: base_filters["commodity"] = commodity
            if st:        base_filters["state"]    = st
            if markets:
                for mk in markets:
                    f = dict(base_filters); f["market"] = mk
                    try: partial.extend(fetch_records(f, limit))
                    except: pass
            else:
                try: partial.extend(fetch_records(base_filters, limit))
                except: pass
        if partial:
            collected = partial
            break

    # clean + convert
    seen, items = set(), []
    def num(x):
        try:
            v = float(str(x).replace(",", "").strip())
            return None if math.isnan(v) else v
        except: return None

    for rec in collected:
        key = (rec.get("commodity",""), rec.get("market",""), rec.get("state",""),
               rec.get("variety",""), rec.get("arrival_date",""))
        if key in seen: 
            continue
        seen.add(key)

        minp  = num(rec.get("min_price"))
        modal = num(rec.get("modal_price"))
        maxp  = num(rec.get("max_price"))

        price_unit = "₹/Quintal"
        if unit == "kg":
            price_unit = "₹/kg"
            minp  = None if minp  is None else minp  / 100.0
            modal = None if modal is None else modal / 100.0
            maxp  = None if maxp  is None else maxp  / 100.0

        items.append({
            "commodity": rec.get("commodity"),
            "variety":   rec.get("variety"),
            "market":    rec.get("market"),
            "district":  rec.get("district"),
            "state":     rec.get("state"),
            "date":      rec.get("arrival_date"),   # DD/MM/YYYY
            "min_price": minp,
            "modal_price": modal,
            "max_price": maxp,
            "unit": price_unit,
            "source": "Agmarknet via data.gov.in"
        })

    def dkey(it):
        try:
            d, m, y = it["date"].split("/")
            return int(f"{y}{m}{d}")
        except: return 0
    items.sort(key=lambda it: (dkey(it), it.get("commodity") or "", it.get("market") or ""), reverse=True)

    return jsonify({"items": items})
