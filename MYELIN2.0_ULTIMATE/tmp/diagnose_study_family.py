from collections import Counter

from GET_CHART.study_family_evidence import (
    _cosecant_break,
    _recorder_statuses,
    _secant_episode,
)
from METRIC_HUB.read_model import _cosecant_metric
from PERSISTENCE.database import database_path
from SCIENCE_LAB.secant_adapter import recorder_readiness
from SECANT.dashboard_evidence import read_corpus
from SECANT.dashboard_projection import project_cosecant, project_secant

p = database_path(create_parent=False)
statuses = _recorder_statuses(p)
snapshots = read_corpus(p)
problems = Counter()
for snapshot in snapshots:
    rows = snapshot.rows("secant_events")
    if rows:
        attached = tuple(x for x in statuses if snapshot.session_id in x.get("attached_session_ids", ()))
        readiness, reason = recorder_readiness(attached, {x["recorder_run_id"] for x in rows})
        if readiness != "AVAILABLE":
            print("SECANT_READINESS", snapshot.session_id, readiness, reason, "receipts", len(attached))
            problems[("secant_readiness", readiness, reason)] += 1
        try:
            episodes = project_secant(snapshot)
            for episode in episodes:
                _secant_episode(episode)
        except Exception as exc:
            print("SECANT_VALIDATION", snapshot.session_id, type(exc).__name__, str(exc))
            for episode in project_secant(snapshot):
                print("  EPISODE", episode.status, episode.founded["recorded_at_utc"] if episode.founded else "NO_START", Counter(r["recording_quality"] for r in episode.events), episode.display_episode_id)
            problems[("secant_validation", type(exc).__name__, str(exc))] += 1
    rows = snapshot.rows("cosecant_events")
    if rows:
        try:
            _cosecant_metric(rows, {snapshot.session_id})
        except Exception as exc:
            print("COSECANT_METRIC", snapshot.session_id, type(exc).__name__, str(exc))
            problems[("cosecant_metric", type(exc).__name__, str(exc))] += 1
        try:
            for item in project_cosecant(snapshot):
                _cosecant_break(snapshot, item)
        except Exception as exc:
            print("COSECANT_PROJECTION", snapshot.session_id, type(exc).__name__, str(exc))
            for item in project_cosecant(snapshot):
                if item["status"] != "AVAILABLE" or item["started"] is None:
                    print("  BREAK", item["status"], item.get("diagnostic"), item["started"].get("occurred_wall_time_utc") if item["started"] else "NO_START", [(r["sequence"], r["kind"]) for r in rows if r["break_id"] == item["native_id"]], item["display_break_id"])
            problems[("cosecant_projection", type(exc).__name__, str(exc))] += 1
print("TOTALS", problems)
