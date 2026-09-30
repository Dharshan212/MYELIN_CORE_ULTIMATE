"""Dashboard export coordination. Worker reads/renders; GUI thread owns dialogs."""
from pathlib import Path

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QFileDialog, QMessageBox
from .pdf_model import build_report


class _Signals(QObject):
    done=pyqtSignal(object)
    failed=pyqtSignal(str)


class _Work(QRunnable):
    def __init__(self,stage,action):
        super().__init__();self.stage=stage;self.action=action;self.signals=_Signals()
    @pyqtSlot()
    def run(self):
        try:self.signals.done.emit((self.stage,self.action()))
        except Exception as error:self.signals.failed.emit(str(error) or type(error).__name__)


class PdfController(QObject):
    finished=pyqtSignal(str)

    def __init__(self,view,scope_reader,timezone_provider,session_provider=lambda:None):
        super().__init__(view)
        self.view=view;self.scope_reader=scope_reader;self.timezone_provider=timezone_provider
        self.session_provider=session_provider
        self.busy=False;self._work=None;self.last_result=None

    def _start(self,stage,action):
        self._work=_Work(stage,action)
        self._work.signals.done.connect(self._done)
        self._work.signals.failed.connect(self._failed)
        QThreadPool.globalInstance().start(self._work)

    @pyqtSlot(object)
    def request(self,selection):
        if self.busy:return
        if not isinstance(selection,dict) or set(selection)-{'secant_identity','study_identity'}:
            self._failed('Unavailable: invalid report selection.');return
        # Immutable intent captured before a worker or dialog can process more UI events.
        try:
            choice={k:tuple(v) for k,v in selection.items()}
            if not choice:
                # Query live engine identity only on the GUI thread, at click time.
                current=self.session_provider()
                if current is not None:choice['session_id']=current
            timezone=self.timezone_provider()
        except Exception:
            self._failed('Unavailable: invalid report scope or timezone.');return
        self.busy=True;self.last_result=None
        self.view.set_export_busy(True,'Reading selected session evidence...')
        self._start('model',lambda:build_report(self.scope_reader(use_current=False,**choice),timezone))

    @pyqtSlot(object)
    def _done(self,result):
        self._work=None
        stage,value=result
        if stage=='model':
            target,_=QFileDialog.getSaveFileName(self.view,
                f'Save Study Recovery Report - Parent Session {value.session_id} (FINALIZED)',
                str(Path.home()/'Downloads'/f'MYELIN_STUDY_RECOVERY_SESSION_{value.session_id}.pdf'), 'PDF documents (*.pdf)',
                options=QFileDialog.Option.DontConfirmOverwrite)
            if not target:self._finish('cancelled','Export cancelled.');return
            path=Path(target)
            if not path.suffix:path=path.with_suffix('.pdf')
            overwrite=False
            if path.exists():
                answer=QMessageBox.question(self.view,'Replace existing PDF?',
                    f'Replace {path.name}? The existing file will remain intact if export fails.',
                    QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)
                if answer!=QMessageBox.StandardButton.Yes:self._finish('cancelled','Export cancelled.');return
                overwrite=True
            self.view.set_export_busy(True,f'Generating Parent Session {value.session_id} PDF...')
            def save():
                from .pdf_renderer import export_report
                return export_report(value,path,overwrite=overwrite)
            self._start('saved',save)
        else:
            self.last_result=value
            self._finish('saved',f'PDF saved: {value.pages} pages.')
            QMessageBox.information(self.view,'Study Recovery Report saved',
                f'Saved {value.pages} pages to:\n{value.path}'+
                ('\nUnsupported characters were substituted and disclosed in the report.' if value.substitutions else ''))

    @pyqtSlot(str)
    def _failed(self,message):
        self._work=None;self._finish('failed','PDF not saved. '+message)
        QMessageBox.warning(self.view,'Study Recovery Report',message)

    def _finish(self,status,message):
        self.busy=False;self.view.set_export_busy(False,message);self.finished.emit(status)
