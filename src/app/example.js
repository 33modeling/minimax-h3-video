// "예시 JSON 받기" 내용. 파일 이름은 파일 칸 2에서 고를 파일과 맞춘다.
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
