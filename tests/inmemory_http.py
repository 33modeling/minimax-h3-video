"""Run existing HTTP handlers in memory; never bind or listen on a socket."""
from contextlib import contextmanager, ExitStack
from email.message import Message
from http import HTTPStatus
import http.server
import io
import errno
import itertools
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request
from unittest.mock import patch


@contextmanager
def transport():
    registry = {}; ports = itertools.count(41000)
    class Server:
        def __init__(self, address, handler, **kwargs):
            port = address[1] or next(ports)
            key = 'http://127.0.0.1:'+str(port)
            if key in registry and registry[key].active:
                raise OSError(errno.EADDRINUSE, 'Address already in use')
            self.server_address = ('127.0.0.1', port)
            self.server_name, self.server_port = self.server_address
            self.handler = handler; self.active = True
            registry['http://127.0.0.1:'+str(self.server_port)] = self
        def serve_forever(self, **kwargs): pass
        def shutdown(self): self.active = False
        def server_close(self): self.active = False

    class Response(io.BytesIO):
        def __init__(self, payload, headers, code, url):
            super().__init__(payload);self.headers=headers;self.status=code;self.url=url
        def getcode(self): return self.status
        def geturl(self): return self.url
        def info(self): return self.headers

    def urlopen(request, data=None, **kwargs):
        if isinstance(request,str): request=urllib.request.Request(request,data=data)
        url=urllib.parse.urlsplit(request.full_url);server=registry.get(url.scheme+'://'+url.netloc)
        if not server or not server.active: raise urllib.error.URLError('in-memory endpoint unavailable')
        body=request.data or b'';handler=server.handler.__new__(server.handler)
        handler.server=server;handler.client_address=('127.0.0.1',12345)
        handler.command=request.get_method();handler.request_version='HTTP/1.1'
        handler.path=urllib.parse.urlunsplit(('', '',url.path or '/',url.query,''))
        handler.headers=Message()
        for key,value in request.header_items():handler.headers[key]=value
        if body and handler.headers.get('Content-Length')is None:handler.headers['Content-Length']=str(len(body))
        handler.rfile=io.BytesIO(body);handler.wfile=io.BytesIO();headers=Message();status=[200]
        def send_response(code,message=None):status[0]=code
        handler.send_response=send_response;handler.send_header=lambda key,value:headers.add_header(key,str(value));handler.end_headers=lambda:None
        def send_error(code,message=None,explain=None):
            status[0]=code;handler.wfile.write((message or HTTPStatus(code).phrase).encode())
        handler.send_error=send_error
        handler.log_request=lambda *args:None
        handler.log_error=lambda *args:None
        handler.log_message=lambda *args:None
        handler.close_connection=True
        handler.connection=type('Connection',(),{'settimeout':lambda *args:None})()
        method=getattr(handler,'do_'+handler.command,None)
        if method:method()
        else:send_error(501)
        payload=handler.wfile.getvalue();response=Response(payload,headers,status[0],request.full_url)
        if status[0]>=400:raise urllib.error.HTTPError(request.full_url,status[0],HTTPStatus(status[0]).phrase,headers,response)
        return response

    with ExitStack()as stack:
        stack.enter_context(patch.object(http.server,'ThreadingHTTPServer',Server))
        stack.enter_context(patch.object(http.server,'HTTPServer',Server))
        stack.enter_context(patch.object(urllib.request,'urlopen',urlopen))
        stack.enter_context(patch.object(socket.socket,'listen',side_effect=AssertionError('No real listeners permitted')))
        stack.enter_context(patch.object(socket,'create_connection',side_effect=AssertionError('No real network permitted')))
        import mock_server
        stack.enter_context(patch.object(mock_server,'ThreadingHTTPServer',Server))
        yield registry
