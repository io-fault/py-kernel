"""
unit executable test
"""
from .. import library as iolib

#@export
def xexport(sector):
	pass

def client_handler(sector, input, output):
	with sector.xact() as xact:
		p = xact.protocol('http', input, output)

	px = p.transactions()
	while px:
		request, input = yield px
		handler = resolve_handler(reqeust)
		sector.dispatch(handler, request, input, p.connect)

# addressable?
#@boot
def coroutine(sector):
	"executed on actuate"

	with sector.xact() as xact:
		p = xact.pipeline(...)

	events = flow.connect_exit()
	while flow.attached:
		for x in (yield events):
			s = io.Sector()
			sector.dispatch(s)
			s.dispatch(client_handler, *x)

	yield flow.events()

class Interface(iolib.Interface):
	"""
	Library interface for managing HTTP client connections.
	"""

	def connect(self, sector_xact, address, port, layer, input, output):
		with self.xact() as xact:
			i, o = xact.connect(address, port)
			p, fi, fo = http.client_v1(xact, i, o)
