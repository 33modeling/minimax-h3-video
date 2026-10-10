// 예시 작업 JSON. "예시 JSON 받기"와 도움말의 예시 불러오기가 쓴다. 파일 이름은 파일 칸 2에서 고를 파일과 맞춘다.
export const EXAMPLE_JOB = {
  base: 'base.mp4',
  sources: ['src1.mp4', { path: 'src2.mp4', start: 0.5, end: 2.5 }],
  template: 'cutaway',
  fit: 'blur',
  resolution: '720x1280',
  max_duration: 60,
  title: '3초 만에 보는 요약',
  captions: ['오늘 할 이야기', { text: '핵심은 이것', start: 3, end: 5.5 }, '끝까지 보세요'],
  bgm: 'bgm.m4a',
  bgm_volume: 0.25,
  original_volume: 1,
  output: 'my-short.mp4',
};

export const EXAMPLES = [
  {
    name: '내 영상 합성 (컷어웨이)',
    note: '가로 기본 영상 사이사이에 소스 2개, 제목·자막·배경음',
    job: EXAMPLE_JOB,
  },
  {
    name: 'AI 생성만 (프롬프트)',
    note: '소스 없이 H3가 8초 장면을 만들고 자막을 얹음',
    job: {
      prompt: 'A tabby cat leaps over a wooden fence at golden hour, slow motion, shallow depth of field, warm cinematic light',
      duration: 8,
      ratio: '9:16',
      title: '고양이의 대점프',
      captions: ['노을 지는 골목', '담장 앞에 선 고양이', '숨을 고르고', '점프!'],
      output: 'cat-jump.mp4',
    },
  },
  {
    name: 'AI + 내 영상 참조 (ref2va)',
    note: '내 영상(src1.mp4)을 동작 참조로 새 장면 생성',
    job: {
      prompt: 'Use <Video 1> as the motion reference: the same person dances on a neon-lit rooftop at night, handheld camera',
      sources: ['src1.mp4'],
      duration: 6,
      title: '옥상 위 네온 댄스',
      captions: ['원본 동작 그대로', '배경만 네온 옥상으로'],
      output: 'neon-dance.mp4',
    },
  },
];
