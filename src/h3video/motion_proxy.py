"""Project-scoped HTTP bridge for the unmodified HyperFrames Studio.

Absolute API/media URLs are namespaced per composition, not selected with a
shared cookie. Two simultaneously opened projects therefore stay independent.
"""
from __future__ import annotations
import http.client
import json
import re
import urllib.parse
from .client import H3Error
from .motion import ID


def bootstrap(prefix, name):
    return '''<script>(()=>{const prefix=PREFIX,project=PROJECT;
const root=/^\\/(?:api(?:\\/|$)|assets\\/|icons\\/|favicon\\.|__hyperframes)/;
const rewrite=value=>{try{const u=new URL(String(value),location.href);if(u.origin===location.origin&&root.test(u.pathname))return prefix+u.pathname+u.search+u.hash;}catch{}return value;};
const canonical=value=>typeof value==='string'?value.replaceAll(location.origin+prefix,location.origin).replaceAll(prefix+'/','/'):value;
const base=Object.getOwnPropertyDescriptor(Node.prototype,'baseURI');if(base?.get)Object.defineProperty(Node.prototype,'baseURI',{...base,get(){return canonical(base.get.call(this));}});
const originalFetch=window.fetch;window.fetch=(input,options)=>originalFetch.call(window,input instanceof Request?new Request(rewrite(input.url),input):rewrite(input),options);
const open=XMLHttpRequest.prototype.open;XMLHttpRequest.prototype.open=function(method,url,...rest){return open.call(this,method,rewrite(url),...rest);};
for(const name of ['EventSource','Worker']){const Original=window[name];if(Original)window[name]=class extends Original{constructor(url,options){super(rewrite(url),options);}};}
const set=Element.prototype.setAttribute;Element.prototype.setAttribute=function(name,value){return set.call(this,name,['src','href','poster','action'].includes(name)?rewrite(value):value);};
const get=Element.prototype.getAttribute;Element.prototype.getAttribute=function(name){const value=get.call(this,name);return ['src','href','poster','action'].includes(name)?canonical(value):value;};
for(const [type,keys]of [[HTMLIFrameElement,['src']],[HTMLMediaElement,['src','currentSrc']],[HTMLImageElement,['src','currentSrc']],[HTMLScriptElement,['src']],[HTMLLinkElement,['href']],[HTMLAnchorElement,['href']]])for(const key of keys){const d=Object.getOwnPropertyDescriptor(type.prototype,key);if(d?.get)Object.defineProperty(type.prototype,key,{...d,get(){return canonical(d.get.call(this));},...(d.set?{set(value){d.set.call(this,rewrite(value));}}:{})});}
for(const key of ['pushState','replaceState']){const old=history[key];history[key]=function(state,title,url){if(url){const u=new URL(url,location.href);if(u.origin===location.origin&&!u.pathname.startsWith('/hyperframes/')){u.searchParams.set('hyperframes',project);url=u.pathname+u.search+u.hash;}}return old.call(this,state,title,url);};}
window.__HF_CLI_TELEMETRY_DISABLED=true;
})();</script>'''.replace('PREFIX', json.dumps(prefix)).replace('PROJECT', json.dumps(name))


def rewrite_text(body, content_type, prefix, name):
    text = body.decode('utf-8')
    if 'json' in content_type:
        # Studio also uses these paths as canonical composition identifiers.
        # Prefixing metadata breaks its media path normalization (preview and
        # waveform/peaks). Network calls are scoped by the injected adapter.
        return body
    # Only rewrite URL literals, never hashed JS application code.
    text = re.sub(r'''((?:src|href|poster|action)\s*=\s*["'])(/(?:api/|assets/|icons/|favicon\.|__hyperframes)[^"']*)''',
                  lambda m: m[1] + prefix + m[2], text, flags=re.I)
    text = re.sub(r'''(url\(\s*["']?)(/(?:api/|assets/|icons/)[^\s)'";]*)''', lambda m: m[1] + prefix + m[2], text)
    if 'text/html' in content_type:
        injection = bootstrap(prefix, name)
        if '<head>' in text:
            text = text.replace('<head>', '<head>' + injection, 1)
        else:
            text = injection + text
    return text.encode()


def motion_route(handler, app, cors_origins):
    """Return True when a namespaced Studio request has been fully handled."""
    url = urllib.parse.urlsplit(handler.path)
    query = urllib.parse.parse_qs(url.query)
    match = re.fullmatch(r'/hyperframes/(hf-[a-f0-9]{32})/proxy(?:/(.*))?', url.path)
    entry = query.get('hyperframes', [None])[0]
    if not match and not entry:
        return False
    name = match[1] if match else entry
    if not ID.fullmatch(str(name)):
        handler._json({'error': '잘못된 모션 프로젝트 ID입니다.'}, 400)
        return True
    suffix = '/' + (match[2] or '') if match else url.path
    if '\\' in suffix or '\x00' in suffix:
        raise H3Error('허용되지 않은 편집기 경로입니다.')
    origin = handler.headers.get('Origin')
    host = handler.headers.get('Host', '')
    if origin and origin not in cors_origins and '*' not in cors_origins and origin not in ('http://' + host, 'https://' + host):
        handler._json({'error': '허용되지 않은 출처입니다.'}, 403)
        return True
    if suffix.startswith(('/api/desktop', '/api/system', '/api/telemetry')):
        handler._json({'error': '이 작업은 영상 maker의 프로젝트에서 지원하지 않습니다.'}, 403)
        return True
    length = int(handler.headers.get('Content-Length', 0))
    if length < 0 or length > 512 * 1024 * 1024:
        handler._json({'error': '파일은 512MB 이하로 준비하세요.'}, 413)
        return True
    data = handler.rfile.read(length) if length else None
    try:
        if name in app.motion.active and handler.command not in ('GET', 'HEAD'):
            handler._json({'error': '영상 출력 중입니다. 먼저 중지한 뒤 수정하세요.'}, 409)
            return True
        port = app.motion.ensure_preview(name)
    except KeyError:
        handler._json({'error': '모션 프로젝트가 없습니다.'}, 404)
        return True
    except H3Error as error:
        handler._json({'error': str(error)}, 503)
        return True
    prefix = '/hyperframes/' + name + '/proxy'
    upstream = http.client.HTTPConnection('127.0.0.1', port, timeout=120)
    try:
        headers = {key: value for key, value in handler.headers.items()
                   if key.lower() in ('content-type', 'range', 'accept', 'if-match', 'if-none-match') or key.lower().startswith(('x-hf-', 'x-hyperframes-'))}
        headers['Origin'] = f'http://127.0.0.1:{port}'
        upstream.request(handler.command, suffix + ('?' + url.query if match and url.query else ''), body=data, headers=headers)
        response = upstream.getresponse()
        content_type = response.getheader('Content-Type', 'application/octet-stream')
        if content_type.startswith('text/event-stream'):
            handler.send_response(response.status)
            handler._cors()
            handler.send_header('Content-Type', content_type)
            handler.send_header('Cache-Control', 'no-store')
            handler.send_header('Connection', 'close')
            handler.end_headers()
            while line := response.readline():
                handler.wfile.write(line)
                handler.wfile.flush()
            return True
        body = response.read()
        # Studio fetches preview HTML to parse clip/media paths. That source
        # must remain canonical; only actual HTML navigations need scoped URLs.
        source_read = ('text/html' in content_type and suffix.startswith('/api/')
                       and handler.headers.get('Sec-Fetch-Dest') not in ('iframe', 'document'))
        if not source_read and any(t in content_type for t in ('text/html', 'text/css', 'application/json')):
            body = rewrite_text(body, content_type, prefix, name)
        handler.send_response(response.status)
        handler._cors()
        for key in ('Content-Disposition', 'Content-Range', 'Accept-Ranges', 'ETag', 'X-File-Version'):
            value = response.getheader(key)
            if value:
                handler.send_header(key, value)
        handler.send_header('Content-Type', content_type)
        handler.send_header('Cache-Control', 'no-store')
        handler.send_header('Content-Length', str(len(body)))
        handler.end_headers()
        if handler.command != 'HEAD':
            handler.wfile.write(body)
        return True
    finally:
        upstream.close()
