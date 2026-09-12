"""Show coverage of the latest successfully ingested map layers."""
import duckdb
from ingest import DB_PATH


def main():
    if not DB_PATH.exists():
        raise SystemExit('No ingest database yet. Run make ingest.')
    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        run = con.execute('SELECT run_id, snapshot_path FROM latest_ingest_run').fetchone()
        if run is None:
            raise SystemExit('No successful ingest yet. Run make ingest.')
        print(f'Snapshot: {run[0]}\nFiles: {run[1]}\nDatabase: {DB_PATH}\n')
        print(f'{"RPC":<6} {"Kind":<10} {"Stage":<18} {"Features":>8}  Layer')
        for rpc, kind, stage, count, path in con.execute('''
            SELECT coalesce(rpc, '-'), kind, stage, feature_count, path
            FROM current_layers ORDER BY kind, rpc, stage, layer_id''').fetchall():
            print(f'{rpc:<6} {kind:<10} {stage:<18} {count:>8}  {path}')
        print('\nInterim eligibility:')
        for row in con.execute('''SELECT category, count(*),
            count(*) FILTER (WHERE likely_eligible = true),
            count(*) FILTER (WHERE likely_eligible = false),
            count(*) FILTER (WHERE likely_eligible IS NULL)
            FROM interim_areas GROUP BY category ORDER BY category''').fetchall():
            print(f'  {row[0]}: {row[1]} total, {row[2]} likely eligible, '
                  f'{row[3]} likely not eligible, {row[4]} unknown')
        missing, invalid = con.execute('''SELECT count(*) FILTER (WHERE geom IS NULL),
            count(*) FILTER (WHERE geometry_valid = false) FROM current_features''').fetchone()
        unmapped = con.execute('SELECT count(*) FROM unmapped_features').fetchone()[0]
        print(f'\nRetained source records: {missing} missing geometry, {invalid} invalid geometry; '
              f'{unmapped} outside selected map filters.')


if __name__ == '__main__':
    main()
