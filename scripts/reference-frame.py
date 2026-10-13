"""Measure frame typography; optionally describe it with a local vision model."""
import base64
import csv
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.request

from PIL import Image


def analyze(v):
    image=Image.open(v['image']).convert('RGB');w,h=image.size
    colors=image.resize((96,96)).quantize(colors=5).convert('RGB').getcolors(96*96)
    palette=['#%02x%02x%02x'%color for count,color in sorted(colors,reverse=True)[:5]]
    overlays,warnings=[],[]
    if shutil.which('tesseract'):
        home=Path(os.environ.get('H3_STUDIO_TOOLS',Path.home()/'.local/share/h3video/studio'))/'tessdata'
        language='kor+eng' if (home/'kor.traineddata').exists() and (home/'eng.traineddata').exists() else 'eng'
        args=['tesseract',v['image'],'stdout','-l',language,'--psm','11']
        if language=='kor+eng': args += ['--tessdata-dir',str(home)]
        result=subprocess.run([*args,'-c','tessedit_create_tsv=1'],capture_output=True,text=True,timeout=45)
        if result.returncode:
            warnings.append('OCR 실패: 프레임을 보며 글자를 직접 수정하세요.')
        else:
            rows=csv.DictReader(io.StringIO(result.stdout),delimiter='\t');lines={}
            for row in rows:
                text=(row.get('text') or '').strip()
                if not text or float(row.get('conf') or -1)<35:continue
                key=tuple(row[k] for k in ('block_num','par_num','line_num'))
                lines.setdefault(key,[]).append(row)
            for words in lines.values():
                x=min(int(r['left']) for r in words);y=min(int(r['top']) for r in words)
                right=max(int(r['left'])+int(r['width']) for r in words);bottom=max(int(r['top'])+int(r['height']) for r in words)
                # Estimate bright/dark text independently from its contrasting background.
                crop=image.crop((x,y,right,bottom));gray=crop.convert('L');hist=gray.histogram()
                light=sum(hist[160:])<sum(hist[:96])
                samples=[p for p in crop.getdata() if (sum(p)/3>180 if light else sum(p)/3<80)]
                color=tuple(round(sum(p[i] for p in samples)/len(samples)) for i in range(3)) if samples else (255,255,255)
                overlays.append(dict(text=' '.join(r['text'] for r in words),box=dict(x=round(x/w,5),y=round(y/h,5),
                                     width=round((right-x)/w,5),height=round((bottom-y)/h,5)),
                                     font_family=v.get('font') or 'Noto Sans CJK KR',source_font_family=None,
                                     font_size_ratio=round(max(.001,(bottom-y)/h),5),font_weight=700,
                                     color='#%02x%02x%02x'%color,style_status='크기·색은 추정값, 글꼴·굵기는 출력 기본값',
                                     confidence=round(sum(float(r['conf']) for r in words)/len(words)/100,3)))
            if language=='eng':warnings.append('한글 OCR 언어팩 미설치: 영문 OCR만 수행했습니다.')
    else:
        warnings.append('OCR 도구 미설치: 화면의 글자를 직접 입력하세요.')
    text=' / '.join(o['text'] for o in overlays)
    description=f'참고 이미지의 {w}×{h} 화면 구도와 색상을 유지. 주요 색상: '+', '.join(palette)
    if text: description+='; 화면에 관측된 글자: '+text
    if v.get('transcript'): description+='; 음성 내용: '+v['transcript']
    engine='FFmpeg frame + Tesseract OCR + measured palette'
    camera='참고 영상과 비교해 카메라 움직임을 지정하세요.'
    endpoint=os.environ.get('H3_REFERENCE_VISION_BASE_URL','').rstrip('/')
    model=os.environ.get('H3_REFERENCE_VISION_MODEL','')
    if endpoint and model:
        try:
            scaled=image.copy();scaled.thumbnail((960,960));buffer=io.BytesIO();scaled.save(buffer,format='JPEG')
            request=dict(model=model,temperature=.1,max_tokens=650,messages=[dict(role='user',content=[
                dict(type='text',text='Describe only the visible scene, subjects, framing, lighting, style and layout of this frame. Do not invent motion from one frame. Return a concise video generation prompt in Korean. Goal: '+str(v.get('goal',''))),
                dict(type='image_url',image_url=dict(url='data:image/jpeg;base64,'+base64.b64encode(buffer.getvalue()).decode()))])])
            headers={'Content-Type':'application/json'}
            if os.environ.get('H3_REFERENCE_VISION_API_KEY'):headers['Authorization']='Bearer '+os.environ['H3_REFERENCE_VISION_API_KEY']
            response=json.load(urllib.request.urlopen(urllib.request.Request(endpoint+'/v1/chat/completions',
                               data=json.dumps(request).encode(),headers=headers),timeout=120))
            message=response['choices'][0]['message']['content']
            if not isinstance(message,str) or not message.strip():raise ValueError('empty description')
            description=message.strip();engine='local vision: '+model+' + Tesseract OCR'
        except Exception:
            warnings.append('로컬 비전 모델에 연결하지 못했습니다. 관측한 프레임·OCR 기반 초안을 저장했습니다.')
    else:
        warnings.append('비전 모델 미연결: 장면 내용은 프레임을 확인하며 보강하세요. OCR·위치·색상은 실제 분석값입니다.')
    prompt=description+('. 출력 의도: '+v['goal'] if v.get('goal') else '')
    video_prompt=prompt+'. 참고 프레임의 구도와 텍스트 영역을 유지하고, 원하는 움직임을 지정한 뒤 생성하세요.'
    image_prompt=prompt+'. Qwen Image Edit: preserve composition, objects and identity.'
    return dict(description=description,video_prompt=video_prompt,image_prompt=image_prompt,engine=engine,
                camera=camera,palette=palette,overlays=overlays,warnings=warnings)


if __name__=='__main__':
    print(json.dumps(analyze(json.load(sys.stdin)),ensure_ascii=False))
