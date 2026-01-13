# test_api.py
import os, requests, json

API = os.getenv("DATA_GOV_API_KEY")
RID = "9ef84268-d588-465a-a308-a864a43d0070"
url = f"https://api.data.gov.in/resource/{RID}"

for d in ("26/09/2025", "25/09/2025", "24/09/2025"):
    try:
        params = {
            "api-key": API,
            "format": "json",
            "limit": 5,
            "filters": json.dumps({"arrival_date": d}),
        }
        r = requests.get(url, params=params, timeout=12)
        print("DATE", d, "STATUS", r.status_code)
        print("RESP PREVIEW:", r.text[:400].replace("\n", " "))
    except Exception as e:
        print("ERROR", e)
