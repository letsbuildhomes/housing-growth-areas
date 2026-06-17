import duckdb
import config

FLU_GROWTH_CODES = list(config.GROWTH_CODES)


def main():
    duck = duckdb.connect(str(config.DB_PATH), read_only=True)
    duck.execute("LOAD spatial;")

    flu_by_rpc = {}
    for row in duck.execute(
        "SELECT rpc, version, COUNT(*) FROM flu_areas WHERE rpc IS NOT NULL AND rpc != '' GROUP BY rpc, version ORDER BY rpc, version"
    ).fetchall():
        rpc, version, count = row
        flu_by_rpc.setdefault(rpc, {})[version or "?"] = count

    flu_growth_by_rpc = {}
    for row in duck.execute(
        "SELECT rpc, version, COUNT(*) FROM flu_areas WHERE rpc IS NOT NULL AND rpc != '' AND flu_code IN ("
        + ",".join("?" for _ in FLU_GROWTH_CODES)
        + ") GROUP BY rpc, version ORDER BY rpc, version",
        FLU_GROWTH_CODES,
    ).fetchall():
        rpc, version, count = row
        flu_growth_by_rpc.setdefault(rpc, {})[version or "?"] = count

    tier_by_rpc = {}
    for row in duck.execute(
        "SELECT rpc, version, COUNT(*) FROM tier_areas WHERE rpc IS NOT NULL AND rpc != '' AND tier_code = '1B' GROUP BY rpc, version ORDER BY rpc, version"
    ).fetchall():
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

    print()
    print(f"  Boundary data")
    print(f"  {'─' * 52}")
    boundary_counts = {}
    for row in duck.execute(
        "SELECT boundary_type, COUNT(*) FROM boundary_areas GROUP BY boundary_type ORDER BY boundary_type"
    ).fetchall():
        bt, cnt = row
        boundary_counts[bt] = cnt
    plural = {"town": "towns", "county": "counties", "rpc": "rpcs"}
    for bt in ["town", "county", "rpc"]:
        cnt = boundary_counts.get(bt, 0)
        print(f"  {plural[bt]:<12} {cnt} features")

    print()
    print(f"  Database")
    print(f"  {'─' * 52}")
    db_size = config.DB_PATH.stat().st_size / (1024 * 1024)
    print(f"  {config.DB_PATH.name:<20} {db_size:.0f} MB")

    for table in ["flu_areas", "tier_areas", "boundary_areas"]:
        cnt = duck.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table:<20} {cnt:>5} rows")

    for table in ["rpc_growth_union", "rpc_tier_union", "overlay_results", "rpc_stats_data", "flu_tier_data"]:
        try:
            cnt = duck.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"  {table:<20} {cnt:>5} rows (materialized)")
        except Exception:
            pass

    duck.close()


if __name__ == "__main__":
    main()
