"""Run an ExtendScript worker in Photoshop: `Photoshop.exe run.jsx`, then wait for the `done`
marker the worker writes. The worker reports through progress.log and result.json."""
import glob
import json
import os
import subprocess
import threading
import time
from pathlib import Path

JSX_DIR = Path(__file__).resolve().parents[1] / "jsx"
MARKERS = ("progress.log", "result.json", "done")


def find_photoshop(explicit=None):
    candidate = explicit or os.environ.get("PHOTOSHOP_EXE")
    if candidate:
        return Path(candidate)
    found = sorted(glob.glob(r"C:\Program Files\Adobe\Adobe Photoshop*\Photoshop.exe"))
    if not found:
        raise FileNotFoundError("Photoshop.exe не найден — укажите путь через --photoshop")
    return Path(found[-1])


def js_literal(obj):
    """JSON is a valid ES3 literal; ensure_ascii keeps run.jsx pure ASCII (Cyrillic -> \\uXXXX)."""
    return json.dumps(obj, ensure_ascii=True)


def write_run_script(worker, job, work_dir):
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    for name in MARKERS:
        (work_dir / name).unlink(missing_ok=True)
    job = dict(job, workDir=work_dir.resolve().as_posix())
    lines = [
        "#target photoshop",
        f"var JOB = {js_literal(job)};",
        f"$.evalFile(new File({js_literal((JSX_DIR / 'common.jsx').as_posix())}));",
        f"$.evalFile(new File({js_literal((JSX_DIR / worker).as_posix())}));",
    ]
    run = work_dir / "run.jsx"
    run.write_text("\n".join(lines) + "\n", encoding="ascii")
    return run


_ONE_AT_A_TIME = threading.RLock()


def run_worker(worker, job, work_dir, photoshop=None, idle_timeout=900, poll=2.0, on_progress=print):
    with _ONE_AT_A_TIME:
        return _run_worker(worker, job, work_dir, photoshop, idle_timeout, poll, on_progress)


def _run_worker(worker, job, work_dir, photoshop=None, idle_timeout=900, poll=2.0, on_progress=print):
    """Launch Photoshop with the worker and block until it finishes. Times out only when
    progress.log has not grown for idle_timeout seconds (big PSDs are slow to open)."""
    run = write_run_script(worker, job, work_dir)
    work_dir = Path(work_dir)
    subprocess.Popen([str(find_photoshop(photoshop)), str(run)])
    progress = work_dir / "progress.log"
    consumed, last_change = 0, time.monotonic()
    while True:
        done = (work_dir / "done").exists()
        if progress.exists():
            text = progress.read_text(encoding="utf-8-sig", errors="replace")
            if len(text) > consumed:
                for line in text[consumed:].splitlines():
                    if line.strip():
                        on_progress(line)
                consumed, last_change = len(text), time.monotonic()
        if done:
            break
        if time.monotonic() - last_change > idle_timeout:
            raise TimeoutError(f"Photoshop не отвечает {idle_timeout} с; журнал: {progress}")
        time.sleep(poll)
    return json.loads((work_dir / "result.json").read_text(encoding="utf-8-sig"))
