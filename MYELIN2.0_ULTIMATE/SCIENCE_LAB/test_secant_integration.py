"""SECANT experiment isolation and report contracts; synthetic facts, no live DB."""
from dataclasses import asdict, replace
from types import MappingProxyType, SimpleNamespace
import json
import unittest
from unittest.mock import patch

from SECANT.dashboard_evidence import EvidenceSnapshot, EvidenceTable, TABLES
from SECANT.read_model import ExactResource, ResourceDisplayMetadata
from SCIENCE_LAB.secant_adapter import (
    _canonical, _digest, certify_source, classify, recorder_readiness,
    read_secant_source, validate_package_rows,
)
from SCIENCE_LAB.evidence import SourceCoverage
from SCIENCE_LAB.analysis import analyze_finalized_session
from SCIENCE_LAB.report_model import adapt_certified_report_input, plan_report_pages
from SCIENCE_LAB.test_phase4_report_integration import make_package, START, END
from SCIENCE_LAB.test_phase2_report_projections import _snapshot, _experiment, UTC

NS = 1_000_000_000
FINAL_STATUS = dict(run_id='run-one', contract_version=1, writer_state='CLOSED',
    final_flush_committed=True, pending=0, closed_at_utc=UTC,
    attached_session_ids=[42], coverage='BOUNDED_OBSERVATION', dropped=0, gap_reasons=[])


def snapshot(*, stages=1, recovered=True, interrupted=False, source=True, caption=True,
             alias=True, count=1, shift=0, incomplete=False):
    rows, sources, aliases = [], [], []
    for index in range(count):
        eid = f'secant-episode-{index}'
        start = 10 + index * 2000 + shift
        stage_at = start
        events = [('SECANT_EPISODE_FOUNDED', start, 1, 'request-1', '', ''),
                  ('SECANT_DISPLAYED', start, 1, 'request-1', '', '')]
        for stage in range(2, stages + 1):
            stage_at += 600 if stage == 2 else 795
            events.append(('SECANT_DISPLAYED', stage_at, stage, f'request-{stage}', '', ''))
        at = stage_at + 1
        events.append(('SECANT_ACTION_INTENT', at, stages, f'request-{stages}', '', 'RETURN TO STUDY'))
        if interrupted:
            events.extend([('SECANT_RETURN_STARTED', at+1, 0, '', 'attempt-old', ''),
                           ('SECANT_RECOVERY_INTERRUPTED', at+4, 0, '', 'attempt-old', 'evidence_gap')])
            at += 5
        if recovered:
            events.extend([('SECANT_RETURN_STARTED', at+1, 0, '', 'attempt-1', ''),
                           ('SECANT_RETURN_VERIFIED', at+11, 0, '', 'attempt-1', ''),
                           ('SECANT_RECOVERY_CLOSED', at+71, 0, '', 'attempt-1', '')])
        if not incomplete:
            events.append(('SECANT_EPISODE_CLOSED', at+71, stages, '', '', 'recovered' if recovered else 'session_end'))
        for ordinal, (name, seconds, stage, request, attempt, reason) in enumerate(events, 1):
            fact = [1, 42, '42:study:1', 'study-target', eid, name, stage, seconds*NS, request, attempt, 'evidence', reason]
            canonical = _canonical(fact)
            row = dict(event_id=_digest(_canonical(['secant-event-v1', fact, ordinal])),
                       contract_version=1, session_id=42, study_context_id='42:study:1',
                       study_target_resource_id='study-target', episode_id=eid, event_name=name,
                       stage=stage, occurred_monotonic_ns=seconds*NS, request_id=request,
                       attempt_id=attempt, evidence_id='evidence', reason=reason, occurrence_ordinal=ordinal,
                       canonical_fact_json=canonical, fact_digest=_digest(canonical),
                       recorder_run_id='run-one', recording_quality='BOUNDED_OBSERVATION', recorded_at_utc=UTC)
            rows.append(row)
            if name == 'SECANT_EPISODE_FOUNDED' and source:
                payload = dict(resource=asdict(ExactResource('BROWSER', 'source-key', 'video', 'video-token')),
                    evidence_id='source-observation', observed_monotonic_ns=seconds*NS,
                    meaning='OFF_TASK', classification='DISTRACTION', territory='VIDEO',
                    confirmed_off_task=True, certified_ott=False)
                if caption:
                    payload['display_metadata'] = asdict(ResourceDisplayMetadata('Recorded browser caption',
                        'Recorded browser caption', 'source-observation', 1, seconds*NS))
                sources.append(dict(event_id=row['event_id'], source_extension_version=1,
                    source_resource_id='source-key', source_evidence_id='source-observation',
                    source_observed_monotonic_ns=seconds*NS, source_evidence_json=_canonical(payload)))
        if alias:
            aliases.append(dict(entity_kind='SECANT', native_id=eid, alias_version=1,
                founding_utc_date='2026-09-15', daily_ordinal=index+1,
                display_alias=f'SEC-15092026-{index+1:02d}'))
    tables = {name: EvidenceTable((), 'AVAILABLE') for name in TABLES}
    for name, data in [('secant_events', rows), ('secant_founding_source', sources), ('presentation_aliases', aliases)]:
        tables[name] = EvidenceTable(tuple(MappingProxyType(r) for r in data), 'AVAILABLE')
    return EvidenceSnapshot(42, MappingProxyType(tables))


def source_for(**kwargs):
    return certify_source(snapshot(**kwargs), (FINAL_STATUS,))


def package_for(source=None, *, start=START, end=END, **kwargs):
    source = source or source_for(**kwargs)
    rows, scope = classify(source, start, end)
    base = make_package()
    return replace(base, experiment_start_monotonic_ns=start, experiment_end_monotonic_ns=end,
        secant_episode_rows=rows, secant_experiment_scope=scope,
        source_coverage=(*base.source_coverage, SourceCoverage('SECANT', source.status, source.reason,
            len(source.episodes) if source.status != 'UNAVAILABLE' else None)),
        limitations=('SECANT: ' + scope.reason,), provenance=(*base.provenance, *scope.provenance))


class SecantCertificationTests(unittest.TestCase):
    def test_stages_and_recovery_variants(self):
        for stages in (1, 2, 3):
            for recovered in (True, False):
                for interrupted in (True, False):
                    with self.subTest(stages=stages, recovered=recovered, interrupted=interrupted):
                        source = source_for(stages=stages, recovered=recovered, interrupted=interrupted)
                        self.assertEqual(source.status, 'AVAILABLE', source.reason)
                        self.assertEqual(source.episodes[0].stage_reached, stages)
                        page = adapt_certified_report_input(package_for(source)).organ_page('SECANT')
                        self.assertIsNotNone(page)
                        self.assertEqual(next(c.value for c in page.snapshot_cards if c.label == 'Recovered episodes'), str(int(recovered)))

    def test_half_open_full_episode_classification(self):
        source = source_for()
        row = source.episodes[0]
        cases = [(row.opening_ns, row.closing_ns+1, 'FULLY_CONTAINED'),
                 (row.opening_ns+1, row.closing_ns+1, 'CROSS_BOUNDARY_OVERLAP'),
                 (row.opening_ns, row.closing_ns, 'CROSS_BOUNDARY_OVERLAP'),
                 (0, row.opening_ns, 'OUTSIDE_WINDOW'),
                 (row.closing_ns+1, row.closing_ns+2, 'OUTSIDE_WINDOW')]
        for start, end, expected in cases:
            rows, scope = classify(source, start, end)
            self.assertEqual(scope.status, expected)
            self.assertEqual(bool(rows), expected == 'FULLY_CONTAINED')

    def test_mixed_overlap_is_disclosed(self):
        source = source_for(count=2)
        rows, scope = classify(source, source.episodes[0].opening_ns+1, END)
        self.assertEqual(len(rows), 1)
        self.assertEqual(scope.cross_boundary_overlap_count, 1)
        self.assertTrue(scope.provenance)
        page = adapt_certified_report_input(package_for(source, start=source.episodes[0].opening_ns+1)).organ_page('SECANT')
        self.assertIn('overlapping', page.overlap_note)

    def test_incomplete_never_ends_at_last_event(self):
        source = source_for(incomplete=True)
        self.assertEqual(source.status, 'UNAVAILABLE')
        self.assertIn('INCOMPLETE', source.reason)
        self.assertFalse(classify(source, START, END)[0])

    def test_pending_and_recording_loss_are_not_behavioural_gap(self):
        for status in [dict(FINAL_STATUS, writer_state='ACTIVE', final_flush_committed=False),
                       dict(FINAL_STATUS, pending=1), dict(FINAL_STATUS, coverage='RECORDING_GAP_DETECTED')]:
            result = certify_source(snapshot(count=0), (status,))
            self.assertEqual(result.status, 'UNAVAILABLE')
        self.assertEqual(source_for(interrupted=True).status, 'AVAILABLE')
        self.assertEqual(recorder_readiness(())[0], 'UNAVAILABLE')
        self.assertEqual(certify_source(snapshot(), (dict(FINAL_STATUS, run_id='other'),)).status, 'UNAVAILABLE')

    def test_optional_legacy_metadata_and_aliases(self):
        for args in [dict(source=False), dict(caption=False), dict(alias=False)]:
            result = source_for(**args)
            self.assertEqual(result.status, 'AVAILABLE', result.reason)
            self.assertIsNotNone(adapt_certified_report_input(package_for(result)).organ_page('SECANT'))
        self.assertEqual(source_for(source=False).episodes[0].source_status, 'NOT_RECORDED')
        self.assertEqual(source_for(caption=False).episodes[0].caption_status, 'NOT_RECORDED')
        self.assertEqual(source_for(alias=False).episodes[0].display_alias, 'Unavailable')
        snap = snapshot()
        tables = dict(snap.tables)
        tables['presentation_aliases'] = EvidenceTable((dict(tables['presentation_aliases'].rows[0], display_alias='SEC-INVALID'),), 'AVAILABLE')
        result = certify_source(EvidenceSnapshot(42, tables), (FINAL_STATUS,))
        self.assertEqual(result.episodes[0].display_alias, 'Unavailable')

    def test_no_evidence_and_source_read_failure(self):
        source = source_for(count=0)
        self.assertEqual(source.status, 'NO_EVIDENCE')
        item = next(r for r in adapt_certified_report_input(package_for(source)).unavailable_organs if r.organ == 'SECANT')
        self.assertEqual(item.status, 'NO_EVIDENCE')
        with patch('SCIENCE_LAB.secant_adapter.sqlite3.connect', side_effect=__import__('sqlite3').OperationalError):
            self.assertEqual(read_secant_source(42, 'missing.db').status, 'UNAVAILABLE')

    def test_corrupt_identity_and_clock_domains_fail_closed(self):
        for key, value in [('fact_digest', 'bad'), ('recorder_run_id', 'other'), ('recording_quality', 'RECORDING_GAP_DETECTED')]:
            snap = snapshot()
            tables = dict(snap.tables)
            rows = list(tables['secant_events'].rows)
            rows[1] = dict(rows[1], **{key: value})
            tables['secant_events'] = EvidenceTable(tuple(rows), 'AVAILABLE')
            self.assertEqual(certify_source(EvidenceSnapshot(42, tables), (FINAL_STATUS,)).status, 'UNAVAILABLE')

    def test_terminal_requires_recovery_and_receipt_session(self):
        self.assertEqual(certify_source(snapshot(), (dict(FINAL_STATUS, attached_session_ids=[99]),)).status, 'UNAVAILABLE')
        source = source_for()
        row = source.episodes[0]
        facts = tuple(f for f in row.events if f.name != 'SECANT_RECOVERY_CLOSED')
        invalid = replace(source, episodes=(replace(row, events=facts),))
        with self.assertRaises(ValueError):
            adapt_certified_report_input(package_for(invalid))

    def test_pdf_cannot_accept_window_leak(self):
        package = package_for()
        with self.assertRaises(ValueError):
            validate_package_rows(package.secant_episode_rows, package.secant_experiment_scope, 99, START, END)
        with self.assertRaises(ValueError):
            adapt_certified_report_input(replace(package, experiment_end_monotonic_ns=11*NS))

    def test_continuations_and_order(self):
        plan = plan_report_pages(adapt_certified_report_input(package_for(count=8, stages=3)))
        self.assertTrue(any(p.kind == 'continuation' and p.organ == 'SECANT' for p in plan.pages))
        self.assertIn('STUDY_ORGANS', [p.page_code for p in plan.pages])
        self.assertEqual([p.physical_page for p in plan.pages], list(range(1, len(plan.pages)+1)))

    def test_full_analysis_pipeline_and_session_isolation(self):
        source = source_for()
        snap = _snapshot()
        snap = replace(snap, secant=source, source_coverage=(*snap.source_coverage,
            SourceCoverage('SECANT', 'AVAILABLE', source.reason, 1)))
        finalized = SimpleNamespace(parent_session_id=42, evidence_snapshot=snap, finalized_at_utc=UTC)
        result = analyze_finalized_session(finalized=finalized, experiments=(_experiment(start=START, end=END),))
        self.assertEqual(result.status, 'CERTIFIED', result.reason)
        self.assertEqual(len(result.package.secant_episode_rows), 1)
        self.assertTrue(any(e.source == 'SECANT' for e in result.package.timeline))
        self.assertEqual(next(r.count for r in result.package.whole_myelin_summary if r.source == 'SECANT'), 1)
        result = analyze_finalized_session(finalized=finalized, experiments=(_experiment(start=END, end=END+NS),))
        self.assertFalse(result.package.secant_episode_rows)
        self.assertFalse(any(e.source == 'SECANT' for e in result.package.timeline))

    def test_live_projection_has_separate_authority(self):
        from SCIENCE_LAB.live_timeline import LiveOrganTimelineProjector
        from SECANT.read_model import StudyScope, RecoveryProjection, RecoveryPhase, TimelineFact
        projector = LiveOrganTimelineProjector()
        projector.begin_experiment(42, 'experiment')
        projection = SimpleNamespace(scope=StudyScope('42:study:1', 'target'), episode_id='episode',
            timeline=(TimelineFact('SECANT_EPISODE_FOUNDED', 10, 'episode'),), frozen_reasons=(),
            recovery=RecoveryProjection(RecoveryPhase.VERIFYING, verification_elapsed_ns=5*NS, verification_target_ns=10*NS))
        state = projector.receive_secant_projection(projection)[0]
        self.assertEqual(state.organ, 'SECANT')
        self.assertEqual(state.stage, 'RETURN')
        self.assertEqual(next(s.progress for s in state.stages if s.stage == 'RETURN'), .5)
        projection.scope = StudyScope('99:study:1', 'target')
        self.assertFalse(projector.receive_secant_projection(projection))


if __name__ == '__main__':
    unittest.main()
