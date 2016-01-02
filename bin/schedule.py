"""
fault scheduling control

Manages the administrative scheduler provided by fault.io service sets (faultd).
"""

import sys
import os
import functools
from .. import libhttp

class HTTP(libhttp.Interface):
	"""
	Control Client
	"""

	def http_request_accept(self, layer, partial=functools.partial, tuple=tuple):
		path_parts = layer.path.decode('utf-8').split('/')

		empty, service_name, *path = path_parts

		request = layer
		request.service_name = service_name
		request.subpath = tuple(path)
		request.managed = self.services.get(service_name)

		response = self.protocol.output_layer()

		ins = self.protocol.distribute
		out = self.protocol.serialize
		out.enqueue(response) # reserve spot in output queue

		out_connect = partial(out.connect, response)

		# conditionally provide flow connection callback.
		if request.length is not None:
			ins_connect = partial(ins.connect, request)
		else:
			# there is no content flow
			ins_connect = None

		path = request.path

		if path == b'/':
			method = functools.partial(self.service_index, self)
		elif path == b'/root/timestamp':
			method = functools.partial(self.http_timestamp, self)
		elif path == b'/fault':
			raise Exception("FAULT")
		else:
			method = self.method(request)

		if method is None:
			response.initiate((b'HTTP/1.1', b'404', b'NOT FOUND'))
			notfound = b'No such resource.'
			response.add_headers([
				(b'Content-Type', b'text/plain'),
				(b'Content-Length', str(len(notfound)).encode('utf-8'),),
			])

			if request.terminal:
				response.add_headers([
					(b'Connection', b'close'),
				])

			if request.content:
				ins_connect(library.Null)

			proc = library.Flow()
			i = library.Iterate()
			proc.requisite(i)
			proc.subresource(self)
			self.requisite(proc)
			out_connect(proc)
			proc.actuate()
			proc.process([(notfound,)])
			proc.terminate()
		else:
			proc = method(request, response, ins_connect, out_connect)
			if proc is not None:
				self.dispatch(proc)

	def http_request_closed(self, layer, flow):
		# called when the input flow of the request is closed
		if flow is not None:
			flow.terminate()

	@classmethod
	def http_accept(Class, spawn, packet):
		"""
		Accept HTTP connections for interacting with the daemon.
		"""

		source, event = packet
		sector = spawn.sector

		# service_name -> ManagedService
		services = sector.controller.services

		# event is a iterable of socket file descriptors
		for fd in event:
			cxn = Class()
			cxn.services = services
			sector.dispatch(cxn)

			with cxn.xact() as xact:
				io = xact.acquire_socket(fd)
				p, fi, fo = libhttp.client_v1(xact, cxn.http_response_accept, cxn.http_response_closed, *io)

				cxn.requisite(p, fi, fo)
				cxn.protocol = p
				fi.process(None)

def initialize(unit):
	from .. import libservice
	route = libservice.identify_route()

	from .. import library

	proc = unit.context.process
	params = proc.invocation.parameters

	ri = route / 'scheduled' / 'if'

	root_sector = library.Sector()
	unit.place(root_sector, "bin", "fio-schedule")
	root_sector.subresource(unit)

	command, *args = params

	requests.host('fio')

	# prepare group by series of requests
	requests.get(target, error, service, command, host='fio', accept="text/xml")
	requests.put(target, source, ...)
	requests.post(target, source, ..., terminal=True)

	# dispatch a pipeline (parallel in http2)
	connection.dispatch(requests)
	yield requests

	root_sector.actuate()

if __name__ == '__main__':
	from .. import library
	library.execute(control = (initialize,))
