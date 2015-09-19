from .. import library

def foo(sector, lib, timeout=defaulttimeout):
	receiver = lib.fs.append("path")

	http = lib.http.allocate() # http context
	xact = http.query("GET", "http://www.google.com/", receiver, headers=..., endpoint=...)

	if xact.failed:
		# try next
		continue
	else:
		yield receiver

	proc = lib.dns.query("A", "host.com")
	yield sector.timeout(dns_timeout, proc):

	qr = proc.product
	for ip in qr:
		yield from doop(ip)

if __name__ == '__main__':
	import sys; from ...development import libtest
	libtest.execute(sys.modules['__main__'])
