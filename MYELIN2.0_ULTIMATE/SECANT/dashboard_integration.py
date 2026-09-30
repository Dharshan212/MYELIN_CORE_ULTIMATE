"""Explicit-refresh application adapter for the frozen dashboard public API."""
from .dashboard_evidence import EvidenceSnapshot, EvidenceTable, TABLES, read_corpus, resolve_scope
from .dashboard_projection import prepare_presentation


class DashboardIntegration:
    """No polling, lifecycle ownership, physiology calls or persistence writes."""

    def __init__(self, view, database_path, session_provider, timezone_provider):
        self.view = view
        self.database_path = database_path
        self.session_provider = session_provider
        self.timezone_provider = timezone_provider
        self.last_model = None
        self.last_error = ''
        self.view.refresh_requested.connect(self.refresh)
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

    def refresh(self):
        """Use the current session; when none is running, the latest recorded one.

        A read failure replaces the affected scope with explicit Unavailable
        values; it never continues presenting an old archive as a fresh read.
        All receiving calls are presentation-only and do not navigate.
        """
        sid = None
        try:
            sid = self.session_provider()
            if sid is not None and (type(sid) is not int or sid <= 0):
                raise ValueError('Invalid selected session')
            timezone = self.timezone_provider()
            corpus = read_corpus(self.database_path)
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
            self.last_error = ''
        except Exception as error:
            # Neither exception strings nor internal/native identifiers reach UI.
            self.last_error = type(error).__name__
            unavailable = EvidenceSnapshot(sid if type(sid) is int and sid > 0 else 1,
                {n: EvidenceTable((), 'UNAVAILABLE') for n in TABLES})
            model = prepare_presentation(unavailable, 'UTC')
            model['context']['source_banner'] = 'UNAVAILABLE · Evidence read failed'
            model['overview']['insights'] = (('Scope','Unavailable'),)+model['overview']['insights'][1:]
            model['secant_empty'] = model['study_empty'] = ('UNAVAILABLE','Historical evidence could not be read.')
        self.apply(model)
        self.last_model = model

    def apply(self, model):
        self.view.set_presentation_context(captions=model['context'])
        for name in ('landing','overview','episodes','distraction_history','study_history','study_evidence','cosecant'):
            getattr(self.view, 'set_'+name+'_data')(**model[name])
        self.view.set_secant_episode_archive(model['secant_archive'], empty_state=model.get('secant_empty'), preserve_state=True)
        self.view.set_study_session_archive(model['study_archive'], empty_state=model.get('study_empty'), preserve_state=True)
