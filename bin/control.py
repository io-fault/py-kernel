"""
faultd control command

Similar to &.service, but works with a running faultd instance.
Communicates with the running daemon using its file system sockets
or an arbitrary endpoint usually protected with a client certificate.
requirement.

Control only issues commands to faultd which may in turn connect
to the service's process in order to issue the actual command.

Control can dispatch commands or wait for their completion.

.control (uri|env) start|restart|stop|reload <service_name> "comment"
.control (uri|env) wait <service_name> # waits until the service's process exits
.control (uri|env) disable|enable <service_name> "comment"
.control (uri|env) signal <service_name> signo "comment"
"""

import sys
import os
import functools
import itertools
import json

from ...internet import libri
from ...routes import library as libroutes

from .. import libcommand
from .. import libhttp
from .. import library as libio
from .. import libservice # fs-socket resolution

def response_collected(sector, request, response, flow):
	events = flow.sequence[0].storage
	for x in itertools.chain(*itertools.chain(*events)):
		sys.stderr.buffer.write(x)
	sys.stderr.write('\n')

def response_endpoint(context, request, response, connect):
	sector = context.sector

	f = libio.Flow()
	f.requisite(libio.Collect.list())
	sector.dispatch(f)

	f.atexit(functools.partial(response_collected, sector, request, response))
	connect(f)

def main(call):
	root_sector = call.sector
	proc = root_sector.context.process

	iparams = proc.invocation.parameters['system']['arguments']

	target, command, *params = iparams
	if params:
		service, *params = params
	else:
		service = None

	if target == 'env':
		# Uses FAULTD_DIRECTORY environment.
		route = libservice.identify_route()

		ri = route / 'root' / 'if'
		struct = {
			'scheme': 'http',
			'host': 'control',
			'query': [],
		}
		endpoint = libio.endpoint('local', ri.fullpath, "0")
	else:
		# URL target; endpoint exists on a remote system.
		struct = libri.parse(target)

		if struct['scheme'] == 'file':
			path = libri.http(struct)
			ri = libroutes.File.from_absolute('/'+'/'.join(struct['path']))
			protocol = 'http'
		else:
			if struct['scheme'] == 'https':
				port = struct.get('port', 440)
			else:
				port = struct.get('port', 80)

			endpoint = libio.endpoint('ip4', struct['host'], port)

	if command != 'index':
		struct['path'] = ['sys', command]
	else:
		struct['path'] = ['sys', '']

	hc = libhttp.Client.open(root_sector, endpoint)

	req = libhttp.Request()
	path = libri.http(struct)

	# The operations performed by .bin.control have side-effects.
	parameters = json.dumps({'service': service}).encode('utf-8')

	req.initiate((b'POST', b'/'+path.encode('utf-8'), b'HTTP/1.1'))
	req.add_headers([
		(b'Host', b'services'),
		(b'Connection', b'close'),
		(b'Accept', b'text/plain'),
		(b'Content-Type', b'application/json'),
		(b'Content-Length', str(len(parameters)).encode('ascii')),
	])

	fi = libio.Flow()
	i = libio.Iterate()
	i.requisite(terminal=True)
	fi.requisite(i)
	root_sector.dispatch(fi)

	hc.http_request(response_endpoint, req, fi)
	fi.process([(parameters,)])

if __name__ == '__main__':
	from .. import library
	libcommand.execute()
