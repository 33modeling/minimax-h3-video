// 화면 안내: 첫 방문 둘러보기(강조 상자 + 말풍선)와 ⓘ 도움말 토글.
const SEEN_KEY = 'shorts.tourSeen.v1';

export const TOUR_STEPS = [
  { sel: '#slotJson', title: '1. 작업 JSON', text: '프롬프트·템플릿·제목·자막을 적은 명세 파일을 고릅니다. 형식은 "예시 JSON 받기"나 ? 도움말의 예시를 보세요.' },
  { sel: '#slotMedia', title: '2. 소스 영상 (없어도 됨)', text: 'JSON이 가리키는 영상·배경음을 함께 고릅니다. 이름이 안 맞는 영상은 소스로, 음악은 배경음으로 씁니다.' },
  { sel: '#settingsPanel', title: '3. 템플릿·해상도', text: '컷어웨이·분할·PIP·몽타주와 해상도·fps·품질을 고릅니다. 바꾸면 JSON에 바로 반영됩니다.' },
  { sel: '#aiPanel', title: '4. AI 생성 서버 연결', text: 'JSON에 prompt가 있으면 내가 띄운 H3 서버(h3video 웹 서버 또는 SGLang)에 장면 생성을 맡깁니다.' },
  { sel: '#claudePanel', title: '5. Claude로 기획 (선택)', text: '아이디어와 API 키를 넣으면 Claude가 작업 JSON을 써서 1번 칸을 채웁니다.' },
  { sel: '#makeArea', title: '6. 만들기와 진행 상태', text: '"만들기"를 누르면 단계와 장면별 진행률이 나옵니다. 언제든 취소할 수 있습니다.' },
  { sel: '#resultArea', title: '7. 결과 내려받기', text: '완성되면 자동으로 내려받고, 여기서 다시 보거나 받을 수 있습니다. 파일은 이 기기 밖으로 나가지 않습니다.' },
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
