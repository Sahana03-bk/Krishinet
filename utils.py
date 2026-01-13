# utils.py
import math

def haversine_km(lat1, lon1, lat2, lon2):
    """Distance in km between two lat/lon points (Haversine)."""
    try:
        R = 6371.0
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
        c = 2*math.atan2(math.sqrt(a), math.sqrt(1-a))
        return R * c
    except Exception:
        return None

def human_time(seconds):
    if seconds is None:
        return "—"
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s//60}m"
    if s < 86400:
        return f"{s//3600}h"
    return f"{s//86400}d"
