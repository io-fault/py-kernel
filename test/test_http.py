import itertools
import json
from .. import http as library
from .. import library as libio
from . import library as libtest

def req(*headers, host=b'test.fault.io', version=b'HTTP/1.1', uri=b'/test/fault.io.http', method=b'GET',
		body=b'', ctype=b'text/plain', chunks=()
	):
	init = b'%s %s %s\r\n' % (method, uri, version)
	additional = [
		(b'Host', host),
	]
	if body:
		l = str(len(body))
		additional.extend([
			(b'Content-Length', l.encode('ascii')),
			(b'Content-Type', ctype),
		])
	elif chunks:
		additional.extend([
			(b'Transfer-Encoding', b'chunked'),
			(b'Content-Type', ctype),
		])
		sizes = [hex(x).encode('ascii')[2:] + b'\r\n' for x in map(len, chunks)]
		body = b''.join((x+y+b'\r\n') for x,y in zip(sizes, chunks))
		body += b'0\r\n\r\n'

	if additional:
		headers = itertools.chain(additional, headers)
	header_data = b'\r\n'.join(map(b'%s: %s'.__mod__, headers))

	return (init + header_data + b'\r\n\r\n' + body,)

def test_fork(test):
	"""
	Validate requests without bodies, sized bodies, and chunked transfers.
	"""
	g = library.fork(library.Request)
	g.send(None)
	r_open, r_close = list(g.send(req()))
	layer = r_open[1]
	test/r_open[0] == libio.FlowControl.initiate
	test/r_close[0] == libio.FlowControl.terminate
	test/True == (r_close[1] is layer)

	test/layer / library.Request
	test/layer.method == b'GET'
	test/layer.path == b'/test/fault.io.http'
	test/layer.version == b'HTTP/1.1'
	test/layer.host == 'test.fault.io'

	# Content-Length body.
	r_open, *body, r_close = list(g.send(req(body=b'content')))
	layer = r_open[1]
	test/r_open[0] == libio.FlowControl.initiate
	test/r_close[0] == libio.FlowControl.terminate
	test/True == (r_close[1] is layer)
	test/layer / library.Request

	test/layer / library.Request
	test/layer.method == b'GET'
	test/layer.path == b'/test/fault.io.http'
	test/layer.version == b'HTTP/1.1'
	test/layer.host == 'test.fault.io'

	total_content = b''
	for event in body:
		test/event[1] == layer
		total_content += b''.join(event[2])
	test/total_content == b'content'

	# Chunked body.
	r_open, *body, r_close = list(g.send(req((b'Connection', b'close'), chunks=(b'first\n', b'second\n'))))
	layer = r_open[1]
	test/r_open[0] == libio.FlowControl.initiate
	test/r_close[0] == libio.FlowControl.terminate
	test/True == (r_close[1] is layer)
	test/layer / library.Request

	test/layer / library.Request
	test/layer.method == b'GET'
	test/layer.path == b'/test/fault.io.http'
	test/layer.version == b'HTTP/1.1'
	test/layer.host == 'test.fault.io'
	test/layer.terminal == True

	total_content = b''
	for event in body:
		test/event[1] == layer
		total_content += b''.join(event[2])
	test/total_content == b'first\nsecond\n'

def test_join(test):
	j = library.join()
	g = library.fork(library.Request)
	g.send(None); j.send(None)

	r = req()
	events = list(g.send(r))
	layer = events[0][1]
	test/b''.join(list(j.send(events))) == r[0]

	r = req(chunks=(b'first\n', b'second\n'))
	events = list(g.send(r))
	layer = events[0][1]
	test/b''.join(list(j.send(events))) == r[0]

	r = req(body=(b'first\n' + b'second\n'))
	events = list(g.send(r))
	layer = events[0][1]
	test/b''.join(list(j.send(events))) == r[0]

def test_Protocol(test):
	"""
	Validate requests without bodies, sized bodies, and chunked transfers.

	More of an integration test as its purpose is to tie &library.fork and
	&library.join together for use with &libio.Transports.
	"""

	ctx = libtest.Context()
	ctl = libtest.Root()
	S = libio.Sector()
	S.context = ctx
	S.controller = ctl
	S.actuate()

	http = library.Protocol.server()
	ti, to = libio.Transports.create((http,))
	fi, fo = libio.Transformation(ti), libio.Transformation(to)
	ic = libio.Collection.list()
	oc = libio.Collection.list()

	S.process((fi, fo, ic, oc))
	fi.f_connect(ic)
	fo.f_connect(oc)

	# Replay of test_fork for sanity.
	fi.process(req())
	r_open, r_close = ic.c_storage[0]
	layer = r_open[1]
	test/r_open[0] == libio.FlowControl.initiate
	test/r_close[0] == libio.FlowControl.terminate
	test/True == (r_close[1] is layer)

	test/layer / library.Request
	test/layer.method == b'GET'
	test/layer.path == b'/test/fault.io.http'
	test/layer.version == b'HTTP/1.1'
	test/layer.host == 'test.fault.io'

if __name__ == '__main__':
	import sys; from ...development import libtest
	libtest.execute(sys.modules[__name__])
