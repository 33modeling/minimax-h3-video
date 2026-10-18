"""One local Qwen Image Edit request; invoked as a cancellable studio child."""
import base64
import json
import os
from pathlib import Path
import sys
import urllib.request
import uuid
import shutil
import tempfile


def edit(v):
    shared=Path(os.environ.get('STORYBOOK_MAKER_ROOT',Path(__file__).resolve().parents[2]/'storybook-maker'))/'scripts/retouch-frame.mjs'
    if shared.is_file() and shutil.which('node'):
        # Replace this process, so studio stop terminates the actual HTTP client
        # and does not leave an image generation running in an orphan child.
        with tempfile.TemporaryFile() as payload:
            payload.write(json.dumps(v).encode());payload.seek(0)
            os.dup2(payload.fileno(),0)
            os.execv(shutil.which('node'),['node',str(shared)])
    from PIL import Image
    turbo=v.get('provider')=='qwen-image-turbo'
    quantized=v.get('provider')=='qwen-image-quantized'
    prefix='QWEN_IMAGE_QUANTIZED' if quantized else 'QWEN_IMAGE_TURBO' if turbo else 'QWEN_IMAGE'
    endpoint=os.environ.get(prefix+'_BASE_URL','http://127.0.0.1:8094' if quantized else 'http://127.0.0.1:8093' if turbo else 'http://127.0.0.1:8091').rstrip('/')
    model=os.environ.get(prefix+'_MODEL','abenzerps/Qwen-Image-2.1-Uncensored-Quantized' if quantized else 'Qwen/Qwen-Image-2.1-Turbo' if turbo else 'Qwen/Qwen-Image-2.1')
    image=Path(v['input']);size=Image.open(image).size
    boundary='qwen-'+uuid.uuid4().hex;parts=[]
    fields=dict(model=model,prompt=v['prompt'],size=f'{size[0]}x{size[1]}',response_format='b64_json',
                seed=str(v.get('seed',0)),num_inference_steps=str(8 if turbo else v.get('steps',40)),true_cfg_scale='1' if turbo else '4')
    for key,value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
    field=os.environ.get(prefix+'_EDIT_FIELD','image')
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="frame.png"\r\nContent-Type: image/png\r\n\r\n'.encode()+image.read_bytes()+b'\r\n')
    parts.append(f'--{boundary}--\r\n'.encode());headers={'Content-Type':'multipart/form-data; boundary='+boundary}
    if os.environ.get(prefix+'_API_KEY'):headers['Authorization']='Bearer '+os.environ[prefix+'_API_KEY']
    try:
        data=json.load(urllib.request.urlopen(urllib.request.Request(endpoint+'/v1/images/edits',data=b''.join(parts),headers=headers),timeout=900))
        item=data['data'][0]
        if item.get('b64_json'):content=base64.b64decode(item['b64_json'],validate=True)
        elif item.get('url'):
            # Fetch only outputs from the configured model origin.
            from urllib.parse import urlparse,urljoin
            url=urljoin(endpoint+'/',item['url'])
            if urlparse(url).netloc!=urlparse(endpoint).netloc:raise ValueError('외부 이미지 URL 응답')
            content=urllib.request.urlopen(url,timeout=60).read()
        else:raise ValueError('이미지 응답 없음')
        out=Path(v['output']);temporary=out.with_suffix('.working.png');temporary.write_bytes(content)
        with Image.open(temporary) as restored:
            restored.load()
            if restored.size!=size:
                raise ValueError('편집 모델이 요청한 프레임 크기를 유지하지 않았습니다.')
            restored.convert('RGB').save(temporary,format='PNG')
        temporary.replace(out)
        print(json.dumps(dict(model=model,width=size[0],height=size[1])))
    except Exception as error:
        import urllib.error
        detail=error.read().decode(errors='replace')[:1500] if isinstance(error,urllib.error.HTTPError) else str(error)
        raise RuntimeError('로컬 Qwen Image Edit 요청 실패. 원본은 보존됩니다. '+type(error).__name__+': '+detail) from None


if __name__=='__main__':edit(json.load(sys.stdin))
