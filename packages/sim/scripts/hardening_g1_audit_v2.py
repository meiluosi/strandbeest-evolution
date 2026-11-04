"""Re-audit all frozen G1 metrics under ADR-0012, without rerunning dynamics.

Missing full traces in a historical cohort are explicitly unverified. Saved
version-1 findings must reproduce exactly; no historical evidence is rewritten.
"""
import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from strandbeest_sim.audit import audit_report
from strandbeest_sim.config import sim_config


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    plan = json.loads(args.plan.read_text())
    sources = {str(p): digest(p) for folder in ['packages/sim/src', 'packages/common/src']
               for p in sorted(Path(folder).rglob('*.py'))}
    sources.update({str(Path(__file__)): digest(__file__), 'schemas/run.schema.json': digest('schemas/run.schema.json')})
    result = {'complete': False, 'plan_path': str(args.plan), 'plan_sha256': digest(args.plan),
              'dynamics_rerun': False, 'source_sha256': sources, 'cohorts': [], 'full_cohort_pass': False}
    for source in plan['inputs']:
        assert digest(source['path']) == source['sha256']
        old = json.loads(Path(source['path']).read_text())
        assert old['complete'] and old['n'] == 64 and old['seed'] == 1
        assert [r['case'] for r in old['rows']] == list(range(64))
        rows = []
        for row in old['rows']:
            assert row['completed']
            report = audit_report(sim_config(row['scenario']), row['metrics'], None,
                                  row['stalled'], backend_name='mujoco')
            assert report['legacy']['findings'] == row['findings'], f"Historical drift: {source['name']}/{row['case']}"
            rows.append({'case': row['case'], 'historical_telemetry_available': False, 'audit': report})
        count = Counter(r['audit']['status'] for r in rows)
        legacy_failures = sum(not r['audit']['legacy']['passed'] for r in rows)
        assert legacy_failures == source['original_failed_cases']
        assert count['passed'] == 0
        cohort = {'source': source, 'rows': rows, 'summary': {'current': dict(count), 'legacy_failed': legacy_failures,
                  'all_64_cases_retained': True, 'all_legacy_findings_exactly_reproduced': True}}
        result['cohorts'].append(cohort)
        print(json.dumps({'cohort': source['name'], **cohort['summary']}), flush=True)
    result['source_drift'] = [p for p, h in sources.items() if digest(p) != h]
    assert not result['source_drift']
    result['complete'] = True
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')


if __name__ == '__main__':
    main()
