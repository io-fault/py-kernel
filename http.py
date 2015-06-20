"""
HTTP transformers and protocols.
"""
from ..internet import libhttp
from ..internet import libmedia
from ..chronometry import library as timelib

from . import core

# XXX: probably split it up into Request and Respond subclasses
class Transaction(object):
	"""
	An HTTP Transaction; common state used by individual HTTP transits.
	"""
	# sent *or* received attributes
	path = None
	method = None

	response_code = None
	response_description = None
	response_version = None
	request_method = None
	request_path = None
	request_version = None

	cached_headers = set(
		x.lower() for x in [
			b'Connection',
			b'Upgrade',
			b'Warning',
			b'Host',

			b'Transfer-Encoding',
			b'Transfer-Extension',

			b'TE',
			b'Trailer',

			b'Date',
			b'Last-Modified',
			b'Retry-After',

			b'Server',
			b'User-Agent',
			b'P3P',

			b'Accept',
			b'Accept-Encoding',
			b'Accept-Language',

			b'Content-Type',
			b'Content-Language',
			b'Content-Length',

			b'Cache-Control',
			b'ETag',
			b'If-Match',
			b'If-Modified-Since',
			b'If-None-Match',
			b'If-Range',
			b'If-Unmodified-Since',

			b'Authorization',
			b'WWW-Authenticate',

			b'Location',
			b'Max-Forwards',

			b'Via',
			b'Vary',
		]
	)

	@property
	def media_range(self):
		"""
		Structured form of the Accept header.
		"""
		pass

	@property
	def date(self, parse = timelib.parse_rfc1123):
		"""
		Date header timestamp.
		"""
		ts = self.headers[b'date'].decode('utf-8')
		return parse(ts)

	@property
	def encoding(self):
		"""
		Encoding header as bytes.
		"""

	@property
	def terminal(self):
		"""
		Whether this is the last request or response in the connection.
		"""
		return self.headers.get(b'connection', b'').strip().lower() == b'close'

	@property
	def cookies(self):
		"""
		Cookie sequence for retrieved Cookie headers or Set-Cookie headers.
		"""
		self.parameters.get('cookies', ())

	def __init__(self, polarity):
		self.polarity = polarity
		self.parameters = dict()
		self.headers = dict()

	@classmethod
	def client(Class, method, path, version = b'HTTP/1.1'):
		r = Class(1)
		r.method = method
		r.path = path
		r.version = ('HTTP', '1.1')

		r.request_method = method.encode('utf-8')
		r.request_path = path.encode('utf-8')
		r.request_version = version
		return r

	@classmethod
	def server(Class):
		r = Class(-1)
		return r

	@property
	def perspective(self):
		return (None, 'client', 'server')[self.polarity]

	def initiation(self, rline):
		"""
		Called when the request or response was received from a remote endpoint.
		"""
		self.remote_line = rline

		if self.perspective == 'client':
			version, response_code, description = rline
			self.response_code = response_code
			self.response_description = description
			self.response_version = version
		elif self.perspective == 'server':
			method, uri_path, version = rline
			self.request_method = method
			self.request_path = uri_path
			self.request_version = version

			self.path = uri_path.decode('utf-8')
			self.method = method.decode('utf-8')
		else:
			raise ValueError("invalid perspective", perspective)

	def accept(self, headers, cookies = False, cache = ()):
		"""
		Accept a set of headers from the remote end.
		"""
		self.header_sequence = headers

		for k, v in self.header_sequence:
			k = k.lower()
			if k in self.cached_headers:
				self.headers[k] = v
			elif k in (b'set-cookie', b'cookie'):
				cookies = self.parameters.setdefault('cookies', list())
				cookies.append(v)
			elif k in cache:
				self.headers[k] = v

		print(self.date)
		print(self.header_sequence)

class Protocol(core.Protocol):
	"""
	The HTTP protocol implementation for io programs. Produces or consumes &Transaction
	instances for request-response cycles.
	"""
	name = 'http'
	Transaction = Transaction

	def __init__(self, perspective):
		self.perspective = perspective

	@classmethod
	def allocate(Class):
		"""
		Allocate a Transaction for submission.
		"""
		return Class.Transaction()

	def pair(self):
		return (core.Generator(), core.Generator())

	def http1_processor(
		self,
		transformer,
		input = b'',
		rline = libhttp.Event.rline,
		headers = libhttp.Event.headers,
		trailers = libhttp.Event.trailers,
		content = libhttp.Event.content,
		chunk = libhttp.Event.chunk,
		violation = libhttp.Event.violation,
		bypass = libhttp.Event.bypass,
		EOH = libhttp.EOH,
		EOM = libhttp.EOM,
	):
		state = libhttp.disassembly() # produces http events
		xact = Transaction.server()

		# get the initial sequence of events
		events = []
		while not events:
			for x in (yield):
				events.extend(state.send(x))
		events = iter(events) # StopIteration is used to signal fetch more

		close_state = False # header Connection: close
		while not close_state:
			local_state = {
				rline: [],
				headers: [],
			}

			headers_received = False
			while not headers_received:
				for x in events:
					local_state[x[0]].extend(x[1])
					if x == EOH:
						headers_received = True
						break
				else:
					# need more for headers
					events = []
					while not events:
						for x in (yield):
							events.extend(state.send(x))
					events = iter(events)

			# got request or status line and headers for this request
			assert len(local_state[rline]) == 3

			xact.initiation(local_state[rline][:3])
			xact.accept(local_state[headers])

			if xact.terminal:
				# Connection: close present.
				# generator will exit when the loop completes
				close_state = True

			# document = self.open(xact) # initialize the document and the response transformers
			if False:
				# wait until the transaction is ready for the document
				transformer.flow.obstruct(xact.ready)
				while not xact.ready():
					for x in (yield):
						input += x

			##
			# local_state is used as a catch all
			# if strictness is desired, it should be implemented here.

			body = [] # XXX: context based allocation
			trailer_sequence = []
			local_state = {
				# handle both chunking and content types
				content: body.append,
				chunk: body.append,
				trailers: trailer_sequence.extend
			}

			request_complete = False
			while not request_complete:
				for x in events:
					if x == EOM:
						request_complete = True
						break

					# not an eof event, so extend state and process as needed
					local_state[x[0]](x[1])
					if trailer_sequence:
						xact.trailer(None) # XXX: Not sure about signalling with these.
					else:
						if body:
							# send a copy of the body onward
							# transformer.route(xact, body)
							transformer.emit(body)
							print(body)
							body = []
							local_state[content] = body.append
							local_state[chunk] = body.append
				else:
					# need more for EOM
					events = []
					while not events:
						for x in (yield):
							events.extend(state.send(x))
					events = iter(events)

		# end of message loop (connection: close header present)
		# handle connection closure

	def http1_emission(self, transformer):
		state = libhttp.assembly() # produces http responses

		event = (yield)

		while True:
			# pass through atm, needs to require events
			transformer.emission(event)
			event = (yield)
