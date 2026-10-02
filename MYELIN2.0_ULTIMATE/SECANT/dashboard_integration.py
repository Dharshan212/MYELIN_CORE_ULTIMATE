"""Explicit-refresh application adapter for the frozen dashboard public API."""
from .dashboard_evidence import EvidenceSnapshot, EvidenceTable, TABLES, read_corpus, resolve_scope
from .dashboard_projection import prepare_presentation


class DashboardIntegration:
    """Explicit read-only presentation; no lifecycle or physiology authority."""

    def __init__(self, view, database_path, session_provider, timezone_provider):
        self.view = view
        self.database_path = database_path
        self.session_provider = session_provider
        self.timezone_provider = timezone_provider
        self.last_model = None
        self.last_error = ''
        self._refresh_worker = None
        self._request_token = None
        self._navigation_token = None
        self._navigation_done = None
        self._delivered_generation = None
        self._delivery_error = ''
        self._closed = False
        self.view.refresh_requested.connect(self.refresh)
        destroyed = getattr(self.view, 'destroyed', None)
        if hasattr(destroyed, 'connect'):
            destroyed.connect(self._view_destroyed)
        signal = getattr(self.view, 'export_requested', None)
        self.pdf_controller = None
        if hasattr(signal, 'connect'):
            from .pdf_controller import PdfController
            self.pdf_controller = PdfController(view, self.read_parent_scope, timezone_provider, session_provider)
            signal.connect(self.pdf_controller.request)

    def read_parent_scope(self, *, session_id=None, secant_identity=None, study_identity=None, use_current=True):
        """Future export boundary: fresh immutable evidence, no widget/last_model authority.

        Explicit historical selections never fall back to the current session.
        This API neither generates a PDF nor changes recorder lifecycle.
        """
        if use_current and all(v is None for v in (session_id, secant_identity, study_identity)):
            session_id = self.session_provider()
        return resolve_scope(read_corpus(self.database_path), session_id=session_id,
                             secant_identity=secant_identity, study_identity=study_identity)

    def _capture_inputs(self):
        """Resolve application-owned providers only on the calling GUI thread."""
        sid = None
        try:
            sid = self.session_provider()
            if sid is not None and (type(sid) is not int or sid <= 0):
                raise ValueError('Invalid selected session')
            return sid, self.timezone_provider(), ''
        except Exception as error:
            return sid, 'UTC', type(error).__name__

    @staticmethod
    def _prepare_model(database_path, sid, timezone, capture_error=''):
        """Pure read/projection; keep the Phase 1 parent/lifetime scope exactly.

        A read failure replaces the affected scope with explicit Unavailable
        values; it never continues presenting an old archive as a fresh read.
        The worker owns its read-only connection and never calls a widget.
        """
        try:
            if capture_error:
                return DashboardIntegration._unavailable_model(sid), capture_error
            corpus = read_corpus(database_path)
            selected = next((s for s in corpus if s.session_id == sid), None) if sid is not None else (corpus[-1] if corpus else None)
            if selected is None:
                if sid is not None:
                    raise ValueError('Selected session is not durably available')
                empty = EvidenceSnapshot(1, {n: EvidenceTable((), 'AVAILABLE') for n in TABLES})
                model = prepare_presentation(empty, timezone)
                model['context']['source_banner'] = 'RECORDED EVIDENCE · No data'
                model['overview']['insights'] = (('Scope','No data'),)+model['overview']['insights'][1:]
            else:
                model = prepare_presentation(selected, timezone)
            archive_models = [prepare_presentation(s, timezone) for s in corpus]
            secant_failed = any(s.tables['secant_events'].status=='UNAVAILABLE' for s in corpus)
            study_failed = any(m['study_facts']['status']=='UNAVAILABLE' for m in archive_models)
            # Reuse native per-parent validation. Only the three SECANT landing
            # cards span history; Recent, Study Resources and analysis keep the
            # selected parent's presentation and explicit export identity.
            recorded = [e for m in archive_models for e in m['secant_facts']]
            eligible = [e for e in recorded if e.summary_eligible]
            lifetime_failed = secant_failed or any(
                s.recorder_receipts.status == 'UNAVAILABLE' for s in corpus)
            note = f'Lifetime finalized validated evidence; {len(recorded)-len(eligible)} recorded episodes excluded'
            if lifetime_failed:
                values = ('Unavailable',) * 3
                note = 'Lifetime evidence unavailable; historical read incomplete'
            elif recorded:
                values = (len(eligible),
                    sum(len(e.named('SECANT_RETURN_VERIFIED')) for e in eligible),
                    sum(len(e.named('SECANT_RECOVERY_INTERRUPTED')) for e in eligible))
            else:
                empty_status = ('Pending' if any(m['recorder_quality']['status'] == 'PENDING' for m in archive_models)
                    else 'Not recorded' if corpus and all(s.tables['secant_events'].status == 'NOT_RECORDED' for s in corpus)
                    else 'No data')
                values = (empty_status,) * 3
            parent_metrics = model['landing']['metrics']
            model['landing']['metrics'] = tuple(
                (metric[0], str(value), note) for metric, value in zip(parent_metrics[:3], values)
            ) + parent_metrics[3:]
            model['secant_archive'] = tuple(r for m in reversed(archive_models) for r in m['secant_archive'])
            model['study_archive'] = tuple(r for m in reversed(archive_models) if m['study_facts']['status'] != 'UNAVAILABLE' for r in m['study_archive'])
            model['archive_diagnostics'] = tuple((s.session_id, name) for s in corpus
                for name, table in s.tables.items() if table.status == 'UNAVAILABLE')
            if secant_failed or study_failed:
                model['context']['source_banner'] += ' · Some historical evidence unavailable'
            model['secant_empty'] = ('UNAVAILABLE','Historical episodes could not be validated.') if secant_failed else None
            model['study_empty'] = ('UNAVAILABLE','Historical Study sessions could not be validated.') if study_failed else None
            for kind, table in (('secant','secant_events'),('study','study_events')):
                if corpus and all(s.tables[table].status=='NOT_RECORDED' for s in corpus):
                    model[kind+'_empty'] = ('NOT RECORDED','Historical evidence was not recorded.')
            return model, ''
        except Exception as error:
            # Neither exception strings nor internal/native identifiers reach UI.
            return DashboardIntegration._unavailable_model(sid), type(error).__name__

    @staticmethod
    def _unavailable_model(sid):
        unavailable = EvidenceSnapshot(sid if type(sid) is int and sid > 0 else 1,
            {n: EvidenceTable((), 'UNAVAILABLE') for n in TABLES})
        model = prepare_presentation(unavailable, 'UTC')
        model['context']['source_banner'] = 'UNAVAILABLE · Evidence read failed'
        model['overview']['insights'] = (('Scope','Unavailable'),)+model['overview']['insights'][1:]
        model['secant_empty'] = model['study_empty'] = ('UNAVAILABLE','Historical evidence could not be read.')
        return model

    def refresh(self):
        """Keep manual refresh synchronous unless a preparation read is active."""
        if self._closed:
            return
        if self._refresh_worker is not None and (
                self._refresh_worker.is_refreshing or self._request_token is not None):
            self._request_async()
            return
        model, self.last_error = self._prepare_model(self.database_path, *self._capture_inputs())
        self.apply(model)
        self.last_model = model

    def _ensure_worker(self):
        if self._refresh_worker is None:
            # Keep the existing pure/manual adapter importable without Qt.
            from CONTROL_STATION.analytics import SharedDashboardRefresh
            self._refresh_worker = SharedDashboardRefresh(lambda: None)
            self._refresh_worker.bundle_ready.connect(self._apply_prepared)
            self._refresh_worker.refresh_failed.connect(self._preparation_failed)
            self._refresh_worker.accepted_completed.connect(self._preparation_completed)
            self._refresh_worker.refreshing_changed.connect(self._refreshing_changed)
        return self._refresh_worker

    def _set_refreshing(self, value):
        setter = getattr(self.view, 'set_refreshing', None)
        if callable(setter):
            try:
                setter(value)
            except RuntimeError:
                # Qt may already have deleted the view during teardown.
                pass

    def _refreshing_changed(self, active):
        if not self._closed and (active or self._request_token is None):
            self._set_refreshing(active)

    def _request_async(self):
        worker = self._ensure_worker()
        token = object()
        self._request_token = token
        self._delivered_generation = None
        self._delivery_error = ''
        sid, timezone, capture_error = self._capture_inputs()
        path = self.database_path
        prepare = DashboardIntegration._prepare_model
        # Only immutable provider values and the pure projection enter a worker.
        provider = lambda: (token, *prepare(path, sid, timezone, capture_error))
        self._set_refreshing(True)
        if not worker.request_refresh(provider=provider):
            self._request_token = None
            self._set_refreshing(False)
            return False
        return True

    def prepare_for_navigation(self, done):
        """Read off-thread and finish only after accepted GUI application.

        The returned cancellation never waits for an in-flight read. A later
        request is serialized through that same reader, with stale delivery
        suppressed before it can touch the view.
        """
        navigation_token = object()
        self._navigation_token = navigation_token
        self._navigation_done = done

        def cancel():
            if self._navigation_token is navigation_token:
                self._navigation_token = None
                self._navigation_done = None
                self._request_token = None
                if self._refresh_worker is not None:
                    self._refresh_worker.invalidate()
                    if not self._refresh_worker.is_refreshing:
                        self._set_refreshing(False)

        if self._closed:
            self._finish_navigation('Closed')
        else:
            try:
                if not self._request_async():
                    self._finish_navigation('Closed')
            except Exception as error:
                cancel()
                self._set_refreshing(False)
                done(False, type(error).__name__)
        return cancel

    def _apply_prepared(self, prepared):
        token, model, error = prepared
        if self._closed or token is not self._request_token:
            return
        generation = self._refresh_worker.generation
        try:
            self.apply(model)
        except Exception as failure:
            error = type(failure).__name__
        else:
            if self._closed or token is not self._request_token:
                return
            self.last_model = model
        if self._closed or token is not self._request_token:
            return
        self.last_error = error
        self._delivery_error = error
        self._delivered_generation = generation

    def _preparation_failed(self, error):
        if not self._closed and self._request_token is not None:
            # Unexpected worker failure has no accepted model to apply.
            self.last_error = 'PreparationError'
            self._delivery_error = self.last_error
            self._delivered_generation = self._refresh_worker.generation

    def _preparation_completed(self, generation, error):
        if (self._closed or self._request_token is None
                or generation != self._delivered_generation):
            return
        self._request_token = None
        self._set_refreshing(False)
        self._finish_navigation(self._delivery_error)

    def _finish_navigation(self, error):
        done = self._navigation_done
        self._navigation_done = None
        self._navigation_token = None
        if done is not None:
            done(not bool(error), error)

    def _view_destroyed(self, *_):
        self.shutdown(timeout=0)

    def shutdown(self, *, timeout=2.0):
        """Stop delivery immediately and give any read a bounded finish budget."""
        self._closed = True
        self._navigation_done = None
        self._navigation_token = None
        self._request_token = None
        if self._refresh_worker is None:
            return True
        self._refresh_worker.invalidate()
        return self._refresh_worker.shutdown(timeout=timeout)

    def apply(self, model):
        self.view.set_presentation_context(captions=model['context'])
        for name in ('landing','overview','episodes','distraction_history','study_history','study_evidence','cosecant'):
            getattr(self.view, 'set_'+name+'_data')(**model[name])
        self.view.set_secant_episode_archive(model['secant_archive'], empty_state=model.get('secant_empty'), preserve_state=True)
        self.view.set_study_session_archive(model['study_archive'], empty_state=model.get('study_empty'), preserve_state=True)
