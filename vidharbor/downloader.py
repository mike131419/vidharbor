"""Desktop queue: runs core.Runner jobs on a Qt thread pool and reports
progress through Qt signals (delivered on the GUI thread)."""
from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, Signal

from .core import (Events, Job, Options, Runner, build_opts, folder_for, friendly,  # noqa: F401
                   job_temp_dir, make_ydl, sniff_page)


class TaskSignals(QObject):
    status = Signal(int, str)
    title = Signal(int, str)
    progress = Signal(int, dict)
    done = Signal(int, str, str, str)   # id, result(ok|error|cancelled), message, filepath
    log = Signal(str)


class _SignalEvents(Events):
    def __init__(self, sig: TaskSignals):
        self.sig = sig

    def status(self, job, text):
        self.sig.status.emit(job.id, text)

    def title(self, job, title):
        self.sig.title.emit(job.id, title)

    def progress(self, job, d):
        self.sig.progress.emit(job.id, d)

    def done(self, job, result, message, filepath):
        self.sig.done.emit(job.id, result, message, filepath)

    def log(self, text):
        self.sig.log.emit(text)


class DownloadTask(QRunnable):
    def __init__(self, job: Job, opts: Options, signals: TaskSignals, direct: bool = False):
        super().__init__()
        self.runner = Runner(job, opts, _SignalEvents(signals), direct=direct)
        self.setAutoDelete(True)

    def run(self):
        self.runner.run()


def run_direct(job: Job, opts: Options, signals: TaskSignals) -> DownloadTask:
    """Task for a stream URL captured by the built-in browser."""
    return DownloadTask(job, opts, signals, direct=True)
