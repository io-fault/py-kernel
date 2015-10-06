"""
fault.io download client.

HTTP client designed for downloading resources to the current working directory.
All requested resources are downloaded in parallel.

XXX: Implicit faultd service (io.fault.cache) rather than command.
"""

import sys
import os
import functools
import itertools
import socket

from ...chronometry import library as timelib
from ...chronometry import libflow
from ...internet import libri
from ...routes import library as routeslib
from ...computation import library as complib

from .. import http
from .. import security
from .. import library
from .. import libinternet

import collections

transfer_counter = collections.Counter()
start_time = None
identities = []
radar = libflow.Radar()

with open('/x/realm/ssl/certs/ca-bundle.crt', 'rb') as f:
	security_context = security.openssl.Context(certificates=[f.read()])

def response_collected(sector, request, response, flow):
	pass

def response_endpoint(sector, request, response, connect, transports=()):
	print(response)
	ri = request.resource_indicator
	if ri["path"]:
		path = routeslib.File.from_path(ri["path"][-1])
	else:
		path = routeslib.File.from_path('index')

	identities.append(path)

	with sector.allocate() as xact:
		target = xact.append(str(path))
		print(target)
		trace = library.Trace()
		track = complib.compose(functools.partial(radar.track, path), complib.sum_lengths)

		trace.monitor("rate", track)
		f = xact.flow((library.Iterate(), trace), target)

	sector.dispatch(f)

	f.atexit(functools.partial(response_collected, sector, request, response))
	connect(f)

def request(struct):
	req = http.Request()
	path = libri.http(struct)

	req.initiate((b'GET', b'/'+path.encode('utf-8'), b'HTTP/1.1'))
	req.add_headers([
		(b'Host', struct['host'].encode('idna')),
		(b'Accept', b'application/octet-stream, */*'),
		(b'User-Agent', b'curl/5.0'),
		(b'Connection', b'close'),
	])

	req.resource_indicator = struct
	return req

def dispatch(sector, url):
	struct, endpoint = url

	req = request(struct)

	if struct['scheme'] == 'https':
		tls = security_context.connect()
		hc = http.Client.open(sector, endpoint, transports=(tls, security.operations(tls)))
	else:
		hc = http.Client.open(sector, endpoint, security_context.rallocate())

	hc.http_request(response_endpoint, req, None)

def process_exit(sector):
	"""
	Initialize exit code based on failures and print
	"""

def status(time=None, next=timelib.Measure.of(second=1)):
	for x in identities:
		radar.track(x, 0)
		units, time = (radar.rate(x, timelib.Measure.of(second=8)))
		seconds = time.select('second')

		if seconds:
			rate = (units / time.select('second'))
			print("%s @ %f KB/sec" %(x, rate / 1024,))

	return next

def initialize(unit):
	os.umask(0o137)
	library.core.Ports.load(unit)

	proc = unit.context.process
	urls = proc.invocation.parameters['system']['arguments']

	# URL target; endpoint exists on a remote system.
	endpoints = [libinternet.endpoint(x) for x in urls]

	# Only load DNS if its needed.
	lendpoints = []
	for struct, x in endpoints:
		if x.protocol == 'domain':
			a = socket.getaddrinfo(x.address, None, family=socket.AF_INET, proto=socket.SOCK_STREAM)
			for i in a:
				ip = i[-1][0]
				y = library.endpoint('ip4', ip, x.port)
			lendpoints.append((struct, y))
		else:
			lendpoints.append((struct, x))

	root_sector = library.Sector()
	unit.place(root_sector, "bin", "http-control")
	root_sector.subresource(unit)
	root_sector.actuate()

	if lendpoints:
		for x in lendpoints:
			dispatch(root_sector, x)
	else:
		root_sector.terminate()

	root_sector.atexit(process_exit)

	global start_time
	start_time = timelib.now()
	unit.scheduler.recurrence(status)

if __name__ == '__main__':
	from .. import library
	library.execute(control = (initialize,))
