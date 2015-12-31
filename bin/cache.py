"""
fault.io download client.

HTTP client designed for downloading resources to the current working directory.
All requested resources are downloaded in parallel.
"""

import sys
import os
import functools
import itertools
import socket
import collections

from ...chronometry import library as libtime
from ...chronometry import libflow
from ...internet import libri
from ...routes import library as libroutes
from ...computation import library as libcomp
from .. import library as libio

from .. import http
from .. import security
from .. import libinternet

transfer_counter = collections.Counter()
start_time = None
identities = []
radar = libflow.Radar()

with open('/x/realm/ssl/certs/ca-bundle.crt', 'rb') as f:
	security_context = security.openssl.Context(certificates=[f.read()])

def response_collected(sector, request, response, flow):
	print('response collected')

def response_endpoint(sector, request, response, connect, transports=(), tls=None):
	print(response)
	if tls:
		print(tls.peer_certificate.subject)
	ri = request.resource_indicator
	if ri["path"]:
		path = libroutes.File.from_path(ri["path"][-1])
	else:
		path = libroutes.File.from_path('index')

	identities.append(path)

	with sector.allocate() as xact:
		target = xact.append(str(path))
		print(target)
		trace = libio.Trace()
		track = libcomp.compose(functools.partial(radar.track, path), libcomp.sum_lengths)

		trace.monitor("rate", track)
		f = xact.flow((libio.Iterate(), trace), target)

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
	struct, endpoint = url # libri.parse(x), internet.libio.Endpoint(y)

	req = request(struct)

	if struct['scheme'] == 'https':
		tls = security_context.connect()
		hc = http.Client.open(sector, endpoint, transports=(tls, security.operations(tls)))
	else:
		tls = None
		hc = http.Client.open(sector, endpoint)

	hc.http_request(functools.partial(response_endpoint, tls=tls), req, None)

def process_exit(sector):
	"""
	Initialize exit code based on failures and print
	"""

def status(time=None, next=libtime.Measure.of(second=1)):
	for x in identities:
		radar.track(x, 0)
		units, time = (radar.rate(x, libtime.Measure.of(second=8)))
		seconds = time.select('second')

		if seconds:
			rate = (units / time.select('second'))
			print("\r%s @ %f KB/sec       " %(x, rate / 1024,), end='')

	return next

def initialize(unit):
	libio.core.Ports.load(unit)

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
				y = libio.endpoint('ip4', ip, x.port)
			lendpoints.append((struct, y))
		else:
			lendpoints.append((struct, x))

	root_sector = libio.Sector()
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
	start_time = libtime.now()
	unit.scheduler.recurrence(status)

if __name__ == '__main__':
	os.umask(0o137)
	libio.execute(control = (initialize,))
