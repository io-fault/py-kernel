"""
Internet support module for fault.io applications.

DNS Lookup support.

Warning: Currently, circumvents library.endpoint() instantiation.
"""

import socket # getaddrinfo

from . import core

from ..internet import libri
from ..internet import library as netlib

class DNS(core.Library):
	"""
	Library managing the dispatch of DNS queries.
	"""

	def query(self, callback, domain):
		"""
		"""
		pass

	@staticmethod
	def process_query(item):
		callback, domain = item
		records = socket.getaddrinfo(domain, 0)

	def actuate(self):
		super().actuate()
		t = core.Thread()
		t.requisite(self.process_query)

def service(service_name):
	# Do not use directly.

	if service_name in netlib.common_services:
		return netlib.common_services[service_name]

	raise NotImplementedError("no system service interface support")
	# Fallback to system?

def endpoint(url, scheme=None, parse=libri.parse):
	"""
	Parse a URL using internet.libri.parse and resolve its endpoint.
	Resolves a default port if one is not provided and notes the
	service (scheme) if the endpoint is a domain name.

	Returns the pair: (struct, endpoint)
	Where struct is the parsed Resource Indicator, and endpoint
	is a &fault.internet.library.Endpoint or &fault.internet.library.Reference.
	"""

	struct = parse(url)

	host = struct['host']
	port = struct.get('port')
	scheme = struct.get('scheme', scheme)

	onlydigits = all(map(str.isdigit, host.split('.', 3)))
	if onlydigits:
		if port is None:
			port = service(struct['scheme'])
		endpoint = netlib.Endpoint.create_ip4(host, port)
	else:
		# either domain or ip6
		if ':' in host:
			# ipv6
			host = host[1:-1]
			if port is None:
				port = service(struct['scheme'])
			endpoint = netlib.Endpoint.create_ip6(host, port)
		else:
			# resolve address
			endpoint = netlib.Reference.from_domain(host, struct['scheme'], port=port)

	return struct, endpoint
