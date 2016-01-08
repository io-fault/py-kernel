"""
HTTP client designed for low-level analysis of HTTP transactions; &.bin.http
is not a user agent as it will not follow redirects, manage cookies, or
generate appropriate Content-Length headers for requests with content.

If the submitted request has content, standard input will be written to
the remote host after writing the headers.

The headers submitted and received will be written to standard error, and
the body will be written to standard out, if any.
"""

import sys
import os
import functools
import collections
import operator

from .. import library as libio

from .. import libhttp
from .. import libcommand

def output_thread(transformer, queue, file):
	"""
	Thread transformer function receiving display transactions and writing to the terminal.
	"""
	write = file.write
	flush = file.flush
	get = queue.get

	while True:
		try:
			while True:
				out = get()
				if out is None:
					flush()
					return

				write(b''.join(out))
				flush()
		except BaseException as exception:
			transformer.context.process.exception(transformer, exception, "Response Output")

def input_thread(transformer, queue, file, partial=functools.partial):
	"""
	Thread transformer function translating input to Character events for &Console.
	"""
	enqueue = transformer.context.enqueue
	emit = transformer.emit

	data = b'x'
	while data:
		data = os.read(file.fileno(), 1024*2)
		enqueue(partial(transformer.inject, (data,)))

def emitted_headers(sector, fo, connect, flow):
	# sequence fo after fe as we want the headers to be displayed
	# above the body.
	connect(fo)

def response_endpoint(protocol, request, response, connect):
	sector = protocol.sector

	with sector.allocate() as xact:
		file = open('/dev/stderr', 'wb')
		fe = xact.flow((libio.Iterate(), libio.Parallel()))
		fe.sequence[0].requisite(terminal=True)
		fe.sequence[1].requisite(output_thread, file)

		if connect is not None:
			file = open('/dev/stdout', 'wb')
			fo = xact.flow((libio.Iterate(), libio.Parallel()))
			fo.sequence[-1].requisite(output_thread, file)
			sector.dispatch(fo)
			fe.atexit(functools.partial(emitted_headers, sector, fo, connect))

	sector.dispatch(fe)
	fe.process([(str(request).encode('ascii'), b'\n', str(response).encode('ascii'), b'\n',)])

def main(call):
	a = libhttp.Agent()
	root_sector = call.sector
	proc = root_sector.context.process

	sysparams = proc.invocation.parameters['system']['arguments']
	protocol, endpoint, port, host, method, path, *options = sysparams

	options = list(map(operator.methodcaller('encode', 'ascii'), options))
	headers = list(zip(options[0::2], options[1::2]))
	provided = set(x[0] for x in headers)

	endpoint = libio.endpoint(protocol, endpoint, port)

	req = libhttp.Request()
	req.initiate((method.encode('ascii'), path.encode('utf-8'), b'HTTP/1.1'))

	req.add_headers([
		(b'Host', host.encode('idna')),
		(b'Connection', b'close'),
	])

	if b'Accept' not in provided:
		req.add_headers(((b'Accept', b'*/*'),))
	req.add_headers(headers)

	hc = libhttp.Client.open(root_sector, endpoint)

	if req.content:
		with root_sector.allocate() as xact:
			file = open('/dev/stdin', 'rb')
			fi = xact.flow((libio.Parallel(),))
			fi.sequence[0].requisite(input_thread, file)
		root_sector.dispatch(fi)
	else:
		fi = None

	hc.http_request(response_endpoint, req, fi)

if __name__ == '__main__':
	os.umask(0o137)
	libcommand.execute()
