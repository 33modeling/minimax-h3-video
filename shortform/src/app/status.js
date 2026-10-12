// 진행 상태 화면: 단계 목록 · 장면 카드 · 문서 제목 · 완료 알림 · aria-live 알림.
export const STAGES = [
  ['validate', '검증'],
  ['connect', '서버 연결'],
  ['queue', '대기열'],
  ['generate', '생성 중'],
  ['download', '다운로드'],
  ['compose', '합성'],
  ['encode', '인코딩'],
  ['done', '완료'],
];
const AI_STAGES = ['connect', 'queue', 'generate', 'download'];

export const STATE_KO = {
  pending: '대기',
  queued: '대기열',
  in_progress: '생성 중',
  running: '생성 중',
  completed: '완료',
  succeeded: '완료',
  failed: '실패',
  error: '실패',
  cancelled: '취소됨',
  downloading: '받는 중',
  reused: '이전 결과 재사용',
};

export const fmtSec = (s) => (s >= 60 ? `${Math.floor(s / 60)}분 ${Math.round(s % 60)}초` : `${Math.max(0, Math.round(s))}초`);

export class StatusView {
  constructor(root, live) {
    this.root = root;
    this.live = live;
    this.baseTitle = document.title;
    this.timer = null;
    this.cards = [];
    root.innerHTML = '';
    this.list = document.createElement('ol');
    this.list.className = 'stages';
    this.items = new Map();
    for (const [key, label] of STAGES) {
      const li = document.createElement('li');
      li.dataset.stage = key;
      li.innerHTML = `<span class="dot" aria-hidden="true"></span><span class="lbl"></span>`;
      li.querySelector('.lbl').textContent = label;
      this.list.append(li);
      this.items.set(key, li);
    }
    this.cardsBox = document.createElement('div');
    this.cardsBox.className = 'scene-cards';
    root.append(this.list, this.cardsBox);
    root.hidden = true;
  }

  start(useAi) {
    this.root.hidden = false;
    this.useAi = useAi;
    this.failed = false;
    for (const [key, li] of this.items) {
      li.className = useAi || !AI_STAGES.includes(key) ? 'todo' : 'skip';
      li.removeAttribute('aria-current');
      li.querySelector('.lbl').textContent = STAGES.find((s) => s[0] === key)[1] + (!useAi && AI_STAGES.includes(key) ? ' (해당 없음)' : '');
    }
    this.cardsBox.replaceChildren();
    this.cards = [];
    clearInterval(this.timer);
    this.timer = setInterval(() => this.tick(), 1000);
  }

  stage(key, extra = '') {
    let passed = true;
    for (const [k, li] of this.items) {
      if (li.classList.contains('skip')) {
        if (k === key) passed = false;
        continue;
      }
      if (k === key) {
        li.className = 'now';
        li.setAttribute('aria-current', 'step');
        passed = false;
      } else {
        li.className = passed ? 'done' : 'todo';
        li.removeAttribute('aria-current');
      }
    }
    const label = STAGES.find((s) => s[0] === key)[1];
    const li = this.items.get(key);
    li.querySelector('.lbl').textContent = extra ? `${label} ${extra}` : label;
    this.announce(`${label}${extra ? ' ' + extra : ''}`);
    this.current = key;
  }

  finish(ok, text) {
    clearInterval(this.timer);
    if (ok) {
      this.stage('done');
      this.items.get('done').className = 'done';
    } else {
      const li = this.items.get(this.current) || this.items.get('validate');
      li.className = 'fail';
      li.querySelector('.lbl').textContent += ' — 실패';
    }
    this.announce(text);
  }

  hide() {
    clearInterval(this.timer);
    this.root.hidden = true;
    this.title(null);
  }

  announce(text) {
    if (this.live && text) this.live.textContent = text;
  }

  title(text) {
    document.title = text ? `${text} · ${this.baseTitle}` : this.baseTitle;
  }

  // 장면 카드
  addScene(i, n, scene) {
    const card = document.createElement('div');
    card.className = 'scene-card';
    card.innerHTML = `
      <div class="sc-head"><strong></strong><span class="badge">대기</span></div>
      <div class="sc-prompt"></div>
      <div class="bar sc-bar indeterminate"><div></div></div>
      <div class="sc-meta"><span class="sc-time">경과 0초</span><span class="sc-eta"></span><span class="sc-retry"></span></div>
      <div class="sc-id" hidden><span>작업 ID <code></code></span><button type="button" class="ghost tiny">복사</button></div>`;
    card.querySelector('strong').textContent = `장면 ${i + 1}/${n} · ${scene.task}`;
    card.querySelector('.sc-prompt').textContent = scene.prompt;
    const c = { el: card, started: null, progress: null, state: 'pending' };
    card.querySelector('.sc-id button').addEventListener('click', async () => {
      const id = card.querySelector('.sc-id code').textContent;
      try {
        await navigator.clipboard.writeText(id);
        card.querySelector('.sc-id button').textContent = '복사됨';
      } catch {
        card.querySelector('.sc-id button').textContent = '복사 안 됨';
      }
      setTimeout(() => (card.querySelector('.sc-id button').textContent = '복사'), 1500);
    });
    this.cards[i] = c;
    this.cardsBox.append(card);
    return c;
  }

  updateScene(i, st) {
    const c = this.cards[i];
    if (!c) return;
    const card = c.el;
    if (st.state) {
      if (!c.started && st.state !== 'pending' && st.state !== 'reused') c.started = Date.now();
      c.state = st.state;
      const b = card.querySelector('.badge');
      b.textContent = STATE_KO[st.state] || st.state;
      b.dataset.state = st.state;
    }
    if (st.id) {
      card.querySelector('.sc-id').hidden = false;
      card.querySelector('.sc-id code').textContent = st.id;
    }
    const bar = card.querySelector('.sc-bar');
    if (st.progress != null && st.progress > 0) {
      c.progress = st.progress;
      bar.classList.remove('indeterminate');
      bar.firstElementChild.style.width = `${Math.round(st.progress * 1000) / 10}%`;
    }
    if (['completed', 'succeeded', 'reused'].includes(c.state)) {
      bar.classList.remove('indeterminate');
      bar.firstElementChild.style.width = '100%';
      c.done = true;
    }
    if (['failed', 'error', 'cancelled'].includes(c.state)) {
      bar.classList.remove('indeterminate');
      bar.classList.add('failed');
      c.done = true;
    }
    card.querySelector('.sc-retry').textContent = st.retry ? `재시도 중(${st.retry}/${st.maxRetry})` : '';
    this.tick();
  }

  tick() {
    for (const c of this.cards) {
      if (!c || !c.started) continue;
      const el = (c.endAt || (c.done ? (c.endAt = Date.now()) : Date.now())) - c.started;
      const card = c.el;
      card.querySelector('.sc-time').textContent = `경과 ${fmtSec(el / 1000)}`;
      const eta = card.querySelector('.sc-eta');
      if (!c.done && c.progress > 0.02) eta.textContent = `남은 시간 약 ${fmtSec(((el / 1000) * (1 - c.progress)) / c.progress)}`;
      else eta.textContent = '';
    }
  }
}

// 완료 알림: 짧은 소리 + (허락했으면) 브라우저 알림
export function notifyDone(text, enabled) {
  if (!enabled) return;
  try {
    const ctx = new AudioContext();
    const o = ctx.createOscillator();
    const g = ctx.createGain();
    o.frequency.value = 880;
    g.gain.setValueAtTime(0.0001, ctx.currentTime);
    g.gain.exponentialRampToValueAtTime(0.2, ctx.currentTime + 0.02);
    g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.5);
    o.connect(g).connect(ctx.destination);
    o.start();
    o.stop(ctx.currentTime + 0.55);
    o.onended = () => ctx.close();
  } catch {
    /* 소리 못 냄 */
  }
  try {
    if (document.hidden && 'Notification' in window && Notification.permission === 'granted') new Notification('숏폼 제작', { body: text });
  } catch {
    /* 알림 못 냄 */
  }
}
