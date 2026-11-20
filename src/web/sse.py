"""Server-Sent Events progress streaming helper."""
import json
import queue
from flask import Response, stream_with_context


def _format_sse(event_id: int, item: dict) -> str:
    stage = item.get('stage', 'progress')
    if stage == 'done':
        event = 'done'
    elif stage == 'error':
        event = 'error'
    elif stage == 'select':
        event = 'select'
    elif stage == 'heartbeat':
        event = 'heartbeat'
    else:
        event = 'progress'
    return (
        f"id: {event_id}\nevent: {event}\n"
        f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
    )


def create_sse_progress() -> tuple:
    """Create a progress queue and a generator for SSE streaming.

    Returns:
        (queue, generator_func) — queue is used by the worker thread
        to push progress dicts; generator_func is passed to Response().

    Note: ``push`` uses non-blocking puts so a disconnected client cannot
    stall the worker thread when the queue fills.
    """
    q = queue.Queue(maxsize=100)

    def generate():
        event_id = 0
        while True:
            try:
                item = q.get(timeout=30)
                if item is None:
                    break
                event_id += 1
                yield _format_sse(event_id, item)
            except queue.Empty:
                event_id += 1
                yield _format_sse(event_id, {'stage': 'heartbeat'})

    def _put(item, *, terminal: bool = False):
        """Non-blocking put; terminal events drop older frames until they fit."""
        attempts = 8 if terminal else 2
        for _ in range(attempts):
            try:
                q.put_nowait(item)
                return
            except queue.Full:
                try:
                    q.get_nowait()
                except queue.Empty:
                    return

    def push(stage: str, detail: str = "", progress: float = 0.0, result=None):
        """Push a progress event to the queue."""
        item = {"stage": stage, "detail": detail, "progress": progress}
        if result is not None:
            item["result"] = result
        _put(item)

    def done(result=None):
        """Signal completion."""
        _put({"stage": "done", "detail": "", "progress": 1.0, "result": result}, terminal=True)
        _put(None, terminal=True)

    def error(message: str):
        """Signal an error."""
        _put({"stage": "error", "message": message, "progress": 0.0}, terminal=True)
        _put(None, terminal=True)

    def select(matches: list):
        """Signal that user selection is needed from a list of matching chats."""
        _put({"stage": "select", "detail": "", "progress": 0.15, "matches": matches}, terminal=True)
        _put(None, terminal=True)

    push.done = done
    push.error = error
    push.select = select

    return push, generate


def job_sse_generator(job, *, replay_logs: bool = True):
    """Yield SSE frames from a ProgressJob subscription (reconnect-safe)."""
    q = job.subscribe(replay_logs=replay_logs)
    event_id = 0
    try:
        while True:
            try:
                item = q.get(timeout=30)
                if item is None:
                    break
                event_id += 1
                yield _format_sse(event_id, item)
                if item.get('stage') in ('done', 'error', 'select'):
                    # Drain sentinel if present, then end.
                    break
            except queue.Empty:
                event_id += 1
                yield _format_sse(event_id, {'stage': 'heartbeat', 'job_id': job.id})
    finally:
        job.unsubscribe(q)


def sse_response(generator) -> Response:
    """Return a Flask Response configured for SSE streaming.

    ``generator`` may be a zero-arg callable (legacy) or an already-built
    iterator from ``job_sse_generator``.
    """
    body = generator() if callable(generator) else generator
    return Response(
        stream_with_context(body),
        content_type='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive',
        }
    )
