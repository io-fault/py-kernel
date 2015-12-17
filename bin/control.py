"""
faultd control command

Similar to &.service, but works with a running faultd instance.
Communicates with the running daemon using its file system sockets
or an arbitrary endpoint usually protected with a client certificate.
requirement.

Control only issues commands to faultd which may in turn connect
to the service's process in order to issue the actual command.

Control can dispatch commands or wait for their completion.

.bin.control service_name dispatch start|restart|stop|reload (HUP) "comment"
.bin.control service_name wait # waits until the service's process exits
.bin.control service_name disable "comment"
.bin.control service_name enable "comment"
.bin.control service_name signal signo "comment"
"""

import sys
import os
import functools
import itertools

from ...internet import libri

from .. import http
from .. import library as libio
from .. import libservice

class HTTP(libio.Sector):
	"""
	Control Client
	"""

	def http_transaction_open(self, layer, partial=functools.partial, tuple=tuple):
		ep, request = self.response_endpoints[0]
		del self.response_endpoints[0]

		ep(self, request, layer, functools.partial(self.protocol.distribute.connect, layer))

	def http_transaction_close(self, layer, flow):
		# called when the input flow of the request is closed
		if flow is not None:
			flow.terminate()

	def http_request(self, endpoint, layer, flow = None):
		"""
		Emit an HTTP request.
		"""

		self.response_endpoints.append((endpoint, layer))

		out = self.protocol.serialize
		out.enqueue(layer)
		out.connect(layer, flow)

	@classmethod
	def open(Class, sector, endpoint):
		"""
		Open an HTTP connection inside the Sector.
		"""

		# event is an iterable of socket file descriptors
		cxn = Class()
		sector.dispatch(cxn)

		with cxn.xact() as xact:
			io = xact.connect(endpoint.protocol, endpoint.address, endpoint.port)

			p, fi, fo = http.client_v1(
				xact, cxn.http_transaction_open, cxn.http_transaction_close, *io)

			cxn.protocol = p
			cxn.process((p, fi, fo))
			cxn.response_endpoints = []
			fi.process(None)

		return cxn

def response_collected(sector, request, response, flow):
	events = flow.sequence[0].storage
	for x in itertools.chain.from_iterable(events):
		if x:
			print(x)

def response_endpoint(sector, request, response, connect):
	f = libio.Flow()
	f.requisite(libio.Collect.list())
	sector.dispatch(f)

	f.atexit(functools.partial(response_collected, sector, request, response))
	connect(f)

def initialize(unit):
	libio.core.Ports.load(unit)

	proc = unit.context.process
	iparams = proc.invocation.parameters['system']['arguments']

	target, service, command, *params = iparams

	if target == 'env':
		# Uses FAULTD_DIRECTORY environment.
		route = libservice.identify_route()

		ri = route / 'root' / 'if'
		struct = {
			'scheme': 'http',
			'host': 'services', # Irrelevant for local host.
			'path': [],
		}
		endpoint = libio.endpoint('local', ri.fullpath, "0")
	else:
		# URL target; endpoint exists on a remote system.
		struct = libri.parse(target)

		if struct['scheme'] == 'file':
			path = libri.http(struct)
			ri = routeslib.File.from_absolute('/'+'/'.join(struct['path']))
			protocol = 'http'

		else:
			if struct['scheme'] == 'https':
				port = struct.get('port', 8080)
			else:
				port = struct.get('port', 80)

			endpoint = libio.endpoint('ip4', struct['host'], port)

	struct['path'].extend((service, command))

	root_sector = libio.Sector()
	unit.place(root_sector, "bin", "fio-control")
	root_sector.subresource(unit)
	root_sector.actuate()

	hc = HTTP.open(root_sector, endpoint)

	req = http.Request()
	path = libri.http(struct)
	print(struct, path)

	req.initiate((b'GET', b'/'+path.encode('utf-8'), b'HTTP/1.1'))
	req.add_headers([
		(b'Host', b'services'),
		(b'Connection', b'close'),
		(b'Accept', b'text/plain'),
	])
	hc.http_request(response_endpoint, req, None)

if __name__ == '__main__':
	from .. import library
	libio.execute(control = (initialize,))
