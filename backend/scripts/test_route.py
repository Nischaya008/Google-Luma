"""
Test: Chandigarh Airport → PEC (same test as Google Maps comparison).
Google Maps shows: 36 min, 18.3 km, 3 different routes.
"""
import httpx
import time
import json

# Same coordinates user tested with
SRC_LAT, SRC_LON = 30.6741923, 76.7909851
DEST_LAT, DEST_LON = 30.7664869, 76.7850788

print("=" * 60)
print("Google Luma V3 Route Test")
print(f"Origin: ({SRC_LAT}, {SRC_LON})")
print(f"Destination: ({DEST_LAT}, {DEST_LON})")
print("=" * 60)

start = time.time()
r = httpx.get(
    "http://localhost:8000/api/v1/routing/routes/compare",
    params={
        "src_lat": SRC_LAT,
        "src_lon": SRC_LON,
        "dest_lat": DEST_LAT,
        "dest_lon": DEST_LON,
    },
    timeout=30,
)
elapsed = time.time() - start

if r.status_code != 200:
    print(f"\nERROR {r.status_code}: {r.text}")
else:
    data = r.json()
    print(f"\nResponse time: {elapsed:.2f}s\n")

    print(f"{'Mode':<12} {'Safety':>8} {'Time':>10} {'Distance':>10} {'Points':>8}")
    print("-" * 52)

    for route in data["routes"]:
        mode = route["mode"]
        safety = route["average_safety_score"]
        time_s = route["estimated_time_seconds"]
        # Approximate distance from geometry points
        pts = len(route["route_geometry"])
        time_min = time_s / 60

        # Calculate actual distance from geometry
        total_dist = 0
        geom = route["route_geometry"]
        for i in range(1, len(geom)):
            import math
            R = 6371
            dlat = math.radians(geom[i]["lat"] - geom[i-1]["lat"])
            dlon = math.radians(geom[i]["lon"] - geom[i-1]["lon"])
            a = math.sin(dlat/2)**2 + math.cos(math.radians(geom[i-1]["lat"])) * math.cos(math.radians(geom[i]["lat"])) * math.sin(dlon/2)**2
            total_dist += R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

        print(
            f"{mode:<12} {safety:>7.3f} "
            f"{time_min:>8.1f}min "
            f"{total_dist:>8.1f}km "
            f"{pts:>7}"
        )

    print(f"\nRankings: {json.dumps(data['rankings'])}")
    print(f"\nTradeoffs:")
    for mode, metrics in data["tradeoff_metrics"].items():
        print(f"  {mode}: time_diff={metrics['time_penalty_seconds']:.0f}s, safety_diff={metrics['safety_gain_absolute']:+.4f}")
