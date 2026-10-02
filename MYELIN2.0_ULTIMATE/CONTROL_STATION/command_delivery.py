"""GUI-polled transport receipts; never an engine acceptance decision."""
from __future__ import annotations

import logging
import weakref


class PendingCommand:
    """Completion is delivered on the controller's GUI thread, exactly once."""

    def __init__(self):
        self.done = False
        self.value = None
        self.error = ""
        self._callbacks = []

    def add_done_callback(self, callback):
        if self.done:
            callback(self)
        else:
            self._callbacks.append(callback)

    def finish(self, value=None, *, error=""):
        if self.done:
            return
        self.done, self.value, self.error = True, value, error
        callbacks, self._callbacks = self._callbacks, []
        for callback in callbacks:
            try:
                callback(self)
            except Exception:
                logging.getLogger(__name__).exception("Command presentation callback failed")

    def result(self):
        if not self.done:
            raise RuntimeError("Command is still awaiting authority")
        if self.error:
            raise RuntimeError(self.error)
        return self.value


def on_popup_reply(receipt, popup, callback):
    """A retired/deleted Qt surface must not apply a delayed acknowledgement."""
    ref = weakref.ref(popup)
    def complete(reply):
        from PyQt6 import sip
        target = ref()
        if target is None or sip.isdeleted(target) or getattr(target, "_retired", False):
            return
        if getattr(target, "_accepted_close", False):
            return
        callback(reply)
    receipt.add_done_callback(complete)
