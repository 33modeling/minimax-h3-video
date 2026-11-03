"""Measured phase counters. ETA is an estimate and never a completion signal."""
import copy
import math
import time


def task_metrics(task, now=None):
    now = time.time() if now is None else now
    phase = copy.deepcopy(task.get('progressInfo') or {})
    running = task.get('status') == 'running'
    active = float(task.get('activeSeconds', 0))
    if running and task.get('runStartedAt') is not None:
        active += max(0, now - task['runStartedAt'])
    phase.update(elapsedSeconds=round(active, 1), clockIncomplete=task.get('clockIncomplete', False),
                 phaseElapsedSeconds=round(max(0, (now if running else task.get('stoppedAt', now)) - phase.get('startedAt', now)), 1),
                 fraction=None, etaSeconds=None, ratePerSecond=None)
    frames = copy.deepcopy(task.get('frameProgress'))
    if frames:
        if not running:
            frames['active'] = {}
            frames['current'] = None
        phase.update(kind='frames', frames=frames)
        completed, total = frames['completed'], frames['total']
        if running and phase.get('phase') in ('retouch', 'upscale'):
            phase['fraction'] = completed / total if total and completed < total else None
            finished = completed - frames.get('cached', 0)
            measured_time = (frames.get('lastCompletedAt') or frames['sessionStartedAt']) - frames['sessionStartedAt']
            if finished >= 2 and measured_time > 0:
                rate = finished / measured_time
                idle = max(0, now - frames['lastCompletedAt'])
                phase['stalled'] = idle > max(60, 3 / rate)
                if not phase['stalled']:
                    phase.update(ratePerSecond=rate, etaSeconds=max(0, (total-completed)/rate))
    if task.get('status') == 'done':
        phase.update(phase='done', label='완료', fraction=1, etaSeconds=None)
    return phase


def generation_metrics(engine, job, now=None):
    now = time.time() if now is None else now
    stage = job.get('stage') or getattr(engine, 'stage', None) or '준비 중'
    if not hasattr(engine, '_steps_done'):
        return dict(kind='generation', phase=stage, label=stage, fraction=None, updatedAt=now)
    completed = max(0, int(getattr(engine, '_steps_done', 0)))
    total = max(1, int(job.get('plan', {}).get('steps', 50)) - 1)
    old = job.get('metrics') or {}
    start, baseline = old.get('stepStartedAt'), old.get('stepBaseline', 0)
    if completed and (start is None or completed < old.get('completed', 0)):
        start, baseline = now, completed
    last = now if completed != old.get('completed', 0) else old.get('lastStepAt')
    fraction = completed / total if stage in ('생성 중', '디노이징') and 0 < completed < total else None
    rate = None
    if start is not None and completed-baseline >= 2 and last and last > start:
        rate = (completed - baseline) / (last-start)
    stalled = bool(last and rate and now-last > max(60, 3/rate))
    if stalled:
        rate = None
    return dict(kind='generation', phase=stage, label=stage, unit='steps',
                completed=min(completed,total), total=total, fraction=fraction,
                stepStartedAt=start, stepBaseline=baseline, lastStepAt=last, stalled=stalled,
                ratePerSecond=rate if fraction is not None else None,
                etaSeconds=(total-completed)/rate if rate and fraction is not None else None,
                phaseStartedAt=job.get('stageStartedAt'),
                phaseElapsedSeconds=round(max(0,now-job.get('stageStartedAt',now)),1),
                elapsedSeconds=round(max(0,now-job.get('started_at',now)),1),
                outputFrames=job.get('plan',{}).get('num_frames'), updatedAt=now,
                retry=(job.get('recovery') or {}).get('attempt',0))


def generation_snapshot(job, now=None):
    """Refresh clocks without reading counters from an engine serving another job."""
    now = time.time() if now is None else now
    result = copy.deepcopy(job.get('metrics'))
    if not result:
        return None
    running = job.get('status') == 'in_progress'
    end = now if running else job.get('finished_at', result.get('updatedAt', now))
    result['elapsedSeconds'] = round(max(0,end-job.get('started_at',end)),1)
    result['phaseElapsedSeconds'] = round(max(0,end-job.get('stageStartedAt',end)),1)
    rate, last = result.get('ratePerSecond'), result.get('lastStepAt')
    if running and rate and last and now-last > max(60,3/rate):
        result.update(stalled=True, ratePerSecond=None, etaSeconds=None)
    if not running:
        result.update(fraction=1 if job.get('status')=='completed' else None,
                      ratePerSecond=None,etaSeconds=None)
    return result


def progress_text(metrics):
    if not metrics:
        return ''
    parts = []
    if metrics.get('unit') == 'steps' and metrics.get('total'):
        parts.append(f"계산 {metrics.get('completed',0)}/{metrics['total']}")
    eta = metrics.get('etaSeconds')
    if isinstance(eta, (int,float)) and math.isfinite(eta) and eta >= 0:
        parts.append(f"계산 남은 약 {math.ceil(eta/60)}분")
    if metrics.get('retry'):
        parts.append(f"재시도 {metrics['retry']}/2")
    return ' · '.join(parts)
