// 화면 안내: 둘러보기(강조 상자 + 말풍선)와 ⓘ 도움말 토글. 둘러보기는 저절로 열지 않고, 처음 온 사람에게 작은 안내만 보인다.
const SEEN_KEY = 'shorts.tourSeen.v1';
const HINT_KEY = 'shorts.tourHint.v1';

export const TOUR_STEPS = [
  { sel: '#startArea', title: '1. 시작 방법 고르기', text: '처음이면 "예시로 해 보기"를 눌러 보세요. 파일이 없어도 예시 영상을 만들어 볼 수 있어요.' },
  { sel: '#dropZone', title: '2. 파일 한꺼번에 넣기', text: '작업 JSON·영상·그림·음악·zip을 여기에 같이 놓으면 알맞은 칸에 나눠 넣어요. 칸 위에 바로 놓아도 돼요.' },
  { sel: '#slots', title: '3. 칸마다 들어간 파일', text: '파일마다 어디에 쓰이는지(기본 영상·배경음·장면 첫 프레임·쓰지 않음) 붙어요. ×로 뺄 수 있어요.' },
  { sel: '#settingsPanel', title: '4. 모양·화질', text: '템플릿 카드로 화면 배치를 고르고 해상도·fps·품질을 정해요. 바꾸면 JSON에 바로 들어가요.' },
  { sel: '#previewWrap', title: '5. 미리보기', text: '만들기 전에 저해상도로 미리 봐요. 막대를 끌거나 "미리보기 재생"을 눌러요.' },
  { sel: '#makeArea', title: '6. 만들기', text: '"만들기"를 누르면 진행률과 남은 시간이 나와요. 언제든 취소할 수 있고, 끝나면 바로 내려받아요.' },
  { sel: '#aiPanel', title: '7. AI 서버·Claude (선택)', text: '글(prompt)로 장면을 만들려면 내 GPU 서버를 연결해요. 아이디어만 있으면 Claude에게 기획을 맡겨요.' },
];

function storage(fn) {
  try {
    return fn(window.localStorage);
  } catch {
    return null;
  }
}

export function tourSeen() {
  return storage((s) => s.getItem(SEEN_KEY)) === '1';
}

// "처음이세요? 1분 둘러보기" 안내를 닫았나
export function hintDismissed() {
  return storage((s) => s.getItem(HINT_KEY)) === '1';
}

export function dismissHint() {
  storage((s) => s.setItem(HINT_KEY, '1'));
}

export class Tour {
  constructor(steps = TOUR_STEPS) {
    this.steps = steps;
    this.i = 0;
    this.onKey = (e) => this.key(e);
    this.onMove = () => this.place();
  }

  start(i = 0) {
    this.close(false);
    this.prevFocus = document.activeElement;
    this.i = i;
    this.shade = document.createElement('div');
    this.shade.className = 'tour-shade';
    this.ring = document.createElement('div');
    this.ring.className = 'tour-ring';
    this.box = document.createElement('div');
    this.box.className = 'tour-box';
    this.box.setAttribute('role', 'dialog');
    this.box.setAttribute('aria-modal', 'true');
    this.box.setAttribute('aria-labelledby', 'tourTitle');
    this.box.tabIndex = -1;
    this.box.innerHTML = `<h3 id="tourTitle"></h3><p></p><div class="tour-nav"><span class="tour-count"></span><button type="button" class="ghost tiny" data-act="skip">건너뛰기</button><button type="button" class="ghost tiny" data-act="prev">이전</button><button type="button" class="primary tiny" data-act="next">다음</button></div>`;
    this.box.addEventListener('click', (e) => {
      const act = e.target.dataset && e.target.dataset.act;
      if (act === 'next') this.go(1);
      else if (act === 'prev') this.go(-1);
      else if (act === 'skip') this.close(true);
    });
    this.shade.addEventListener('click', () => this.close(true));
    document.body.append(this.shade, this.ring, this.box);
    document.addEventListener('keydown', this.onKey, true);
    window.addEventListener('resize', this.onMove);
    window.addEventListener('scroll', this.onMove, true);
    this.show();
  }

  show() {
    const st = this.steps[this.i];
    const target = document.querySelector(st.sel);
    if (target && target.tagName === 'DETAILS') target.open = true;
    this.box.querySelector('h3').textContent = st.title;
    this.box.querySelector('p').textContent = st.text;
    this.box.querySelector('.tour-count').textContent = `${this.i + 1} / ${this.steps.length}`;
    this.box.querySelector('[data-act=prev]').disabled = this.i === 0;
    this.box.querySelector('[data-act=next]').textContent = this.i === this.steps.length - 1 ? '끝' : '다음';
    if (target) target.scrollIntoView({ block: 'center', behavior: 'instant' });
    this.place();
    this.box.focus();
  }

  place() {
    if (!this.box) return;
    const st = this.steps[this.i];
    const target = document.querySelector(st.sel);
    const vw = document.documentElement.clientWidth;
    const vh = window.innerHeight;
    const M = 12;
    const bw = Math.min(360, vw - 2 * M);
    this.box.style.width = `${bw}px`;
    if (!target) {
      this.ring.style.display = 'none';
      this.box.style.left = `${(vw - bw) / 2}px`;
      this.box.style.top = `${M}px`;
      return;
    }
    const r = target.getBoundingClientRect();
    this.ring.style.display = 'block';
    const pad = 6;
    const left = Math.max(2, r.left - pad);
    const top = Math.max(2, r.top - pad);
    this.ring.style.left = `${left}px`;
    this.ring.style.top = `${top}px`;
    this.ring.style.width = `${Math.min(vw - 4, r.right + pad) - left}px`;
    this.ring.style.height = `${Math.min(vh - 4, r.bottom + pad) - top}px`;
    const bh = this.box.offsetHeight;
    let y = r.bottom + pad + 10;
    if (y + bh > vh - M) y = r.top - pad - 10 - bh; // 위에 둘 자리
    if (y < M) y = Math.max(M, vh - bh - M); // 둘 다 안 되면 화면 아래쪽에
    let x = r.left + r.width / 2 - bw / 2;
    x = Math.max(M, Math.min(vw - bw - M, x));
    this.box.style.left = `${Math.round(x)}px`;
    this.box.style.top = `${Math.round(y)}px`;
  }

  go(d) {
    const n = this.i + d;
    if (n >= this.steps.length) return this.close(true);
    if (n < 0) return;
    this.i = n;
    this.show();
  }

  key(e) {
    if (!this.box) return;
    if (e.key === 'Escape') {
      e.preventDefault();
      this.close(true);
    } else if (e.key === 'ArrowRight') this.go(1);
    else if (e.key === 'ArrowLeft') this.go(-1);
    else if (e.key === 'Tab') {
      // 말풍선 안에서만 돌게
      const btns = [...this.box.querySelectorAll('button:not(:disabled)')];
      const idx = btns.indexOf(document.activeElement);
      e.preventDefault();
      const next = e.shiftKey ? (idx <= 0 ? btns.length - 1 : idx - 1) : (idx + 1) % btns.length;
      btns[next].focus();
    }
  }

  close(markSeen) {
    if (!this.box) return;
    this.shade.remove();
    this.ring.remove();
    this.box.remove();
    this.box = null;
    document.removeEventListener('keydown', this.onKey, true);
    window.removeEventListener('resize', this.onMove);
    window.removeEventListener('scroll', this.onMove, true);
    if (markSeen) storage((s) => s.setItem(SEEN_KEY, '1'));
    if (this.prevFocus && this.prevFocus.focus) this.prevFocus.focus();
    if (this.onClose) this.onClose();
  }
}

// ⓘ 버튼: 누르면 바로 아래에 설명 줄을 펼친다(작은 화면에서도 넘치지 않게 문서 흐름 안에 둔다).
export function setupTips(root = document) {
  root.querySelectorAll('button.tip').forEach((b) => {
    const id = `tip-${Math.random().toString(36).slice(2, 8)}`;
    const p = document.createElement('span');
    p.className = 'tip-text';
    p.id = id;
    p.hidden = true;
    p.textContent = b.dataset.tip;
    b.setAttribute('aria-expanded', 'false');
    b.setAttribute('aria-controls', id);
    b.setAttribute('aria-label', `도움말: ${b.dataset.tip}`);
    b.title = b.dataset.tip;
    b.after(p);
    b.addEventListener('click', (e) => {
      e.preventDefault();
      p.hidden = !p.hidden;
      b.setAttribute('aria-expanded', String(!p.hidden));
    });
  });
}
