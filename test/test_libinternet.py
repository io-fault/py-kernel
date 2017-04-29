from .. import libinternet as library
from ...internet import library as netlib

def test_endpoint(test):
	# Don't bother testing the struct must as it's ri return.

	struct, ep = library.endpoint("https://fault.io")
	test/ep == netlib.Reference(('domain', 'fault.io', 443, 'https'))
	test/struct != None

	struct, ep = library.endpoint("http://fault.io/some/path")
	test/ep == netlib.Reference(('domain', 'fault.io', 80, 'http'))
	test/struct != None

	struct, ep = library.endpoint("https://127.0.0.1")
	test/ep == netlib.Endpoint.create_ip4("127.0.0.1", 443)
	test/struct != None

	struct, ep = library.endpoint("http://[::1]")
	test/ep == netlib.Endpoint.create_ip6("::1", 80)
	test/struct != None

if __name__ == '__main__':
	import sys; from ...development import libtest
	libtest.execute(sys.modules['__main__'])

