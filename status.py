import sqlite3
import config

FLU_GROWTH_CODES = list(config.GROWTH_CODES)


def main():
    conn = sqlite3.connect(str(config.DB_PATH))

    flu_by_rpc = {}
    for row in conn.execute(
        "SELECT rpc, version, COUNT(*) FROM flu_areas WHERE rpc IS NOT NULL AND rpc != '' GROUP BY rpc, version ORDER BY rpc, version"
    ):
        rpc, version, count = row
        flu_by_rpc.setdefault(rpc, {})[version] = count

    flu_growth_by_rpc = {}
    for row in conn.execute(
        "SELECT rpc, version, COUNT(*) FROM flu_areas WHERE rpc IS NOT NULL AND rpc != '' AND flu_code IN ("
        + ",".join("?" for _ in FLU_GROWTH_CODES)
        + ") GROUP BY rpc, version ORDER BY rpc, version",
        FLU_GROWTH_CODES,
    ):
        rpc, version, count = row
        flu_growth_by_rpc.setdefault(rpc, {})[version] = count

    tier_by_rpc = {}
    for row in conn.execute(
        "SELECT rpc, version, COUNT(*) FROM tier_areas WHERE rpc IS NOT NULL AND rpc != '' AND tier_code = '1B' GROUP BY rpc, version ORDER BY rpc, version"
    ):
        rpc, version, count = row
        key = "PRE" if version == "PRE" else "APP" if version == "APP" else "?"
        tier_by_rpc.setdefault(rpc, {})[key] = count

    all_rpcs = sorted(
        set(list(flu_by_rpc.keys()) + list(tier_by_rpc.keys()) + list(config.RPC_CODES.keys()))
    )

    total_flu = sum(sum(v.values()) for v in flu_by_rpc.values())
    total_flu_growth = sum(sum(v.values()) for v in flu_growth_by_rpc.values())
    total_tier_pre = sum(d.get("PRE", 0) for d in tier_by_rpc.values())
    total_tier_app = sum(d.get("APP", 0) for d in tier_by_rpc.values())
    total_tier_unk = sum(d.get("?", 0) for d in tier_by_rpc.values())

    print()
    print(f"  Data coverage by RPC ({total_flu} FLU, {total_flu_growth} growth, {total_tier_pre + total_tier_app + total_tier_unk} tier 1B)")
    print(f"  {'─' * 52}")
    print(f"  {'RPC':<5} {'FLU':<5} {'Growth':<8} {'Tier PRE':<9} {'Tier APP':<9} {'Tier ?':<8} {'Total T1B'}")
    print(f"  {'─' * 52}")
    for rpc in all_rpcs:
        flu = "✓" if rpc in flu_by_rpc else ""
        growth = "✓" if rpc in flu_growth_by_rpc else ""
        tp = tier_by_rpc.get(rpc, {}).get("PRE", 0) or ""
        ta = tier_by_rpc.get(rpc, {}).get("APP", 0) or ""
        tu = tier_by_rpc.get(rpc, {}).get("?", 0) or ""
        tt = (int(tp or 0) + int(ta or 0) + int(tu or 0)) or ""
        print(f"  {rpc:<5} {flu:<5} {growth:<8} {str(tp):<9} {str(ta):<9} {str(tu):<8} {tt}")
    print(f"  {'─' * 52}")
    print(f"  Tier 1B summary: {total_tier_pre} pre, {total_tier_app} app, {total_tier_unk} unknown")
    print(f"  FLU coverage: {sum(1 for r in flu_by_rpc)}/{len(all_rpcs)} RPCs  |  Growth: {sum(1 for r in flu_growth_by_rpc)}/{len(all_rpcs)}")
    print()

    conn.close()


if __name__ == "__main__":
    main()
