"""
# Internet support for io applications.

# Provides DNS resolvers and endpoint construction facilities.
"""

from ..internet import ri
from ..internet import library as libi

def service(service_name):
	# Do not use directly.

	if service_name in libi.common_services:
		return libi.common_services[service_name]

	raise NotImplementedError("no system service interface support")
	# Fallback to system?

def endpoint(url, scheme=None, parse=ri.parse):
	"""
	# Parse a URL using internet.ri.parse and resolve its endpoint.
	# Resolves a default port if one is not provided and notes the
	# service (scheme) if the endpoint is a domain name.

	# Returns the pair: (struct, endpoint)
	# Where struct is the parsed Resource Indicator, and endpoint
	# is a &..internet.library.Endpoint or &..internet.library.Reference.
	"""

	struct = parse(url)

	host = struct['host']
	port = struct.get('port')
	scheme = struct.get('scheme', scheme)

	onlydigits = all(map(str.isdigit, host.split('.', 3)))
	if onlydigits:
		if port is None:
			port = service(struct['scheme'])
		endpoint = libi.Endpoint.create_ip4(host, port)
	else:
		# either domain or ip6
		if ':' in host:
			# ipv6
			host = host[1:-1]
			if port is None:
				port = service(struct['scheme'])
			endpoint = libi.Endpoint.create_ip6(host, port)
		else:
			# resolve address
			endpoint = libi.Reference.from_domain(host, struct['scheme'], port=port)

	return struct, endpoint
