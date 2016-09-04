"""
IETF HTTP support for &..io based applications.

&.libhttp provides foundations for clients and servers. The high-level
concepts are managed by &..web.libhttpd.

[ Properties ]

/HeaderSequence
	Type annotation for the header sequence used by &Layer instances,
	&Layer.header_sequence.
"""
import typing
import functools
import collections
import itertools

import operator

from ..computation import library as libc
from ..chronometry import library as libtime
from ..routes import library as libroutes

from ..internet import libhttp
from ..internet import libmedia

from ..system import libmemory
from . import library as libio

length_string = libc.compose(operator.methodcaller('encode', 'utf-8'), str, len)
length_strings = libc.compose(operator.methodcaller('encode', 'utf-8'), str, sum, functools.partial(map,len))
HeaderSequence = typing.Sequence[typing.Tuple[bytes, bytes]]

class ProtocolTransaction(tuple):
	"""
	The set of objects associated with a protocol transaction.

	&ProtocolTransactions are used for both clients and servers.
	For servers, &interface and &host should be referenced, whereas
	for clients, &agent and &context should be referenced.
	"""
	__slots__ = ()

	ig = operator.itemgetter

	# For agent transactions.
	connection = property(ig(0))
	request = property(ig(1))
	response = property(ig(2))
	connect_input = property(ig(3))
	connect_output = property(ig(4))
	host = property(ig(5))

	del ig

	def reflect(self):
		"""
		Send the input back to the output. Usually, after configuring the response layer.

		Primarily used for performance testing.
		"""

		f = libio.Flow()
		self.connection.dispatch(f)
		self.connect_output(f)
		self.connect_input(f)

	def write_null(self):
		"""
		Used to send a request or a response without a body.
		Necessary to emit the headers of the transaction.
		"""
		self.connect_output(None)

	def read_null(self):
		"""
		Used to note that no read will occur.
		*Must* be used when no body is expected. Usually called by the &Client or &Server.
		"""
		self.connect_input(None)

	def iterate_output(self, iterator:typing.Iterable):
		"""
		Construct a Flow consisting of a single &libio.Iterate instance
		used to stream output to the connection protocol state.

		The &libio.Flow will be dispatched into the &Connection for proper
		fault isolation in cases that the iterator produces an exception.
		"""
		global libio

		i = libio.Iteration(iterator)
		self.connection.dispatch(i)
		self.response.initiate((self.request.version, b'200', b'OK'))
		self.connect_output(i)

		return f

	def write_output(self, mime:str, data:bytes):
		"""
		Send the given &data to the remote end with the given &mime type.
		If other headers are desired, they *must* be configured before running
		this method.
		"""
		global length_string

		self.response.add_headers([
			(b'Content-Type', mime.encode('utf-8')),
			(b'Content-Length', length_string(data)),
		])

		self.iterate_output([(data,)])

	def read_file_into_output(self, path:str, str=str):
		"""
		Send the file referenced by &path to the remote end as
		the (HTTP) entity body.

		The response must be properly initialized before invoking this method.

		[ Parameters ]
		/path
			A string containing the file's path.
		"""
		global libio, libmemory

		f = libio.Iteration(((x,) for x in libmemory.Segments.open(str(path))))
		self.connection.dispatch(f)

		self.connect_output(f)

		return f

	def read_input_into_coroutine(self):
		"""
		Contructs an awaitable iterator that can be used inside
		a coroutine to read the data sent from the remote endpoint.
		"""
		raise NotImplementedError("coroutine support")

	def read_input_into_buffer(self, callback, limit=None):
		"""
		Connect the input Flow to a buffer that executes
		the given callback when the entity body has been transferred.

		This should only be used when connecting to trusted hosts.
		"""

		cxn = self.connection
		f = libio.Collection.buffer()
		cxn.dispatch(f)
		f.atexit(callback)
		self.connect_input(f)

		return f

	def read_input_into_file(self, route):
		"""
		Connect the input Flow's entity body to the given file.

		The file will be truncated and data will be written in append mode.
		"""

		cxn = self.connection
		t, = cxn.context.append_files(str(route))
		f = libio.Transformation(*libio.meter_output(t))
		cxn.dispatch(f)
		self.connect_input(f)

		return f

	def write_kport_to_output(self, fd, limit=None):
		"""
		Transfer data from the &kport, file descriptor to the output
		constrained by the limit.

		The file descriptor will be closed after the transfer is complete.
		"""

		cxn = self.connection
		t, = cxn.context.connect_input(fd)
		f = libio.Transformation(*libio.meter_input(t))
		cxn.dispatch(f)
		self.connect_output(f)

		return f

	def read_input_into_kport(self, fd, limit=None):
		"""
		Connect the input Flow's entity body to the given file descriptor.
		The state of the open file descriptor will be used to allow inputs
		to be connected to arbitrary parts of a file.

		The file descriptor will be closed after the transfer is complete.
		"""

		cxn = self.connection
		t, = cxn.context.connect_output(fd)
		f = libio.Transformation(*libio.meter_output(t))
		cxn.dispatch(f)

		self.connect_input(f)
		return f

	def connect_pipeline(self, kpipeline):
		"""
		Connect the input and output to a &..system.library.KPipeline.
		Received data will be sent to the pipeline,
		and data emitted from the pipeline will be sent to the remote endpoint.
		"""

		cxn = self.connection
		with cxn.allocate() as xact:
			sp, i, o, e = xact.pipeline(kpipeline)
			fi, fo = self.flows()
			fi.requisite(i)
			fo.requisite(o)

		self.connect_input(fi)
		self.connect_output(fo)
		return f

	def proxy(self, endpoint):
		"""
		Fulfill the transaction by transparently proxying the request.
		"""
		pass

class Path(libroutes.Route):
	"""
	A Path sequence used to aid in request routing and request path construction.
	"""

	def __str__(self):
		return '/' + '/'.join(self.absolute)

	@property
	def index(self):
		"""
		Whether the Path is referrring to a directory index. (Ends with a slash)
		"""
		if self.points:
			return self.points[-1] == ""
		else:
			self.absolute[-1] == ""

class Layer(libio.Layer):
	"""
	The HTTP layer of a connection; superclass of &Request and &Response that provide
	access to the parameters of a &Transaction.

	[ Properties ]

	/cached_headers
		The HTTP headers that will be available inside a &dict instance
		as well as the canonical header sequence.

	/(&HeaderSequence)`header_sequence`
		The sequence of headers.

	/(dict)`headers`
		The mapping of headers available in the &header_sequence.

	/channel
		The stream identifier. For HTTP/2.0, this identifies channel
		being used for facilitating the request or response.
	"""

	protocol = 'http'
	version = 1
	channel = None

	@property
	def content(self):
		"Whether the Layer Context is associated with content."
		return self.length is not None

	@property
	def length(self):
		"""
		The length of the content; positive if exact, &None if no content, and -1 if arbitrary.
		For HTTP, arbitrary using chunked transfer encoding is used.
		"""

		cl = self.headers.get(b'content-length')
		if cl is not None:
			return int(cl.decode('ascii'))

		te = self.headers.get(b'transfer-encoding')
		if te is not None and te.lower().strip() == b'chunked':
			return -1

		# no entity body
		return None

	cached_headers = set(
		x.lower() for x in [
			b'Connection',
			b'Upgrade',
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
	def connection(self):
		"""
		Return the connection header stripped and lowered or `b''` if no header present.
		"""
		return self.headers.get(b'connection', b'').strip().lower()

	@staticmethod
	@functools.lru_cache(32)
	def media_range_cache(range_data, parse_range=libmedia.Range.from_bytes):
		global libmedia

		if range_data is not None:
			return parse_range(range_data)
		else:
			return libmedia.any_range # HTTP default.

	@property
	def media_range(self):
		"""
		Structured form of the Accept header.
		"""
		return self.media_range_cache(self.headers.get(b'accept'))

	@property
	def media_type(self) -> libmedia.Type:
		"""
		"""
		global libmedia
		return libmedia.type_from_string(self.headers[b'content-type'].decode('utf-8'))

	@property
	def date(self, parse=libtime.parse_rfc1123) -> libtime.Timestamp:
		"""
		Date header timestamp.
		"""

		if not b'date' in self.headers:
			return None

		ts = self.headers[b'date'].decode('utf-8')
		return parse(ts)

	@property
	def host(self) -> str:
		return self.headers.get(b'host').decode('idna')

	@property
	def encoding(self) -> str:
		"""
		Character encoding of entity content. &None if not applicable.
		"""
		pass

	@property
	def terminal(self) -> bool:
		"""
		Whether this is the last request or response in the connection.
		"""

		cxn = self.connection

		if self.version == b'1.0' and cxn != b'keep-alive':
			return True

		return cxn == b'close'

	@property
	def substitution(self) -> bool:
		"""
		Whether or not the request looking to perform protocol substitution.
		"""

		return self.connection == b'upgrade'

	@property
	def cookies(self) -> typing.Sequence:
		"""
		Cookie sequence for retrieved Cookie headers or Set-Cookie headers.
		"""

		self.parameters.get('cookies', ())

	def clear(self):
		"""
		Clear all structures used to make up the Layer Context;
		&initiate will need to be called again.
		"""
		self.parameters.clear()
		self.headers.clear()
		self.initiation = None
		self.header_sequence.clear()

	def __init__(self):
		self.parameters = dict()
		self.headers = dict()
		self.initiation = None
		self.header_sequence = []

	def __str__(self):
		init = " ".join(x.decode('utf-8') for x in (self.initiation or ()))
		heads = "\n\t".join(x.decode('utf-8') + ': ' + y.decode('utf-8') for (x,y) in self.header_sequence)
		return init + "\n\t" + heads

	def initiate(self, rline:typing.Tuple[bytes,bytes,bytes]):
		"""
		Define the Request or Response initial line.

		Called when the request or response was received from a remote endpoint.
		"""
		self.initiation = rline

	def add_headers(self, headers, cookies = False, cache = ()):
		"""
		Accept a set of headers from the remote end or extend the sequence to
		be sent to the remote end..
		"""

		self.header_sequence += headers

		for k, v in self.header_sequence:
			k = k.lower()
			if k in self.cached_headers:
				self.headers[k] = v
			elif k in {b'set-cookie', b'cookie'}:
				cookies = self.parameters.setdefault('cookies', list())
				cookies.append(v)
			elif k in cache:
				self.headers[k] = v

	def trailer(self, headers):
		"""
		Destination of trailer-headers received during chunked transfer encoding.
		"""
		pass

class Request(Layer):
	"""
	Request portion of an HTTP transaction
	"""

	@property
	def method(self):
		return self.initiation[0]

	@property
	def path(self):
		return self.initiation[1]

	@property
	def version(self):
		return self.initiation[2]

	def declare_without_content(self, method:bytes, path:bytes, version:bytes=b'HTTP/1.1'):
		self.initiate((method, path.encode('utf-8'), version))

	def declare_with_content(self, method:bytes, length:int, path:bytes, version:bytes=b'HTTP/1.1'):
		self.initiate((method, path.encode('utf-8'), version))
		hs = self.header_sequence
		hm = self.headers

		if length is not None:
			if length < 0:
				raise ValueError("content length must be >= 0 or None")

			hs.append((b'Content-Length', str(length).encode('ascii')))
			hm[b'Content-Length'] = length
		else:
			# initialize chunked headers
			hs.append((b'Transfer-Encoding', b'chunked'))
			hm[b'transfer-encoding'] = b'chunked'

	@property
	def GET(self, partial=functools.partial):
		"""
		Initialize as a GET request.
		"""
		return partial(self.declare_without_content, b'GET')

	@property
	def HEAD(self, partial=functools.partial):
		"""
		Initialize as a HEAD request.
		"""
		return partial(self.declare_without_content, b'HEAD')

	@property
	def DELETE(self, partial=functools.partial):
		"""
		Initialize as a DELETE request.
		"""
		return partial(self.declare_without_content, b'DELETE')

	@property
	def TRACE(self, partial=functools.partial):
		"""
		Initialize as a TRACE request.
		"""
		return partial(self.declare_without_content, b'TRACE')

	@property
	def CONNECT(self, partial=functools.partial):
		"""
		Initialize as a CONNECT request.
		"""
		return partial(self.declare_without_content, b'CONNECT')

	@property
	def POST(self, partial=functools.partial):
		"""
		Initialize as a POST request.
		"""
		return partial(self.declare_with_content, b'POST')

	@property
	def PUT(self, partial=functools.partial):
		"""
		Initialize as a PUT request.
		"""
		return partial(self.declare_with_content, b'PUT')

class Response(Layer):
	"""
	Response portion of an HTTP transaction.
	"""

	@property
	def version(self):
		return self.initiation[0]

	@property
	def code(self):
		return self.initiation[1]

	@property
	def description(self):
		return self.initiation[2]

	def result(self, code, description, version=b'HTTP/1.1'):
		self.initiate((version, str(code).encode('ascii'), description.encode('utf-8')))

def join(
		checksum=None,

		rline=libhttp.Event.rline,
		headers=libhttp.Event.headers,
		trailers=libhttp.Event.trailers,
		content=libhttp.Event.content,
		chunk=libhttp.Event.chunk,
		EOH=libhttp.EOH,
		EOM=libhttp.EOM,

		repeat=itertools.repeat,
		zip=zip,

		fc_initiate=libio.FlowControl.initiate,
		fc_terminate=libio.FlowControl.terminate,
		fc_transfer=libio.FlowControl.transfer,
	):
	"""
	Join &libio.Catenate flow events into a proper HTTP stream.
	"""

	serializer = libhttp.assembly()
	serialize = serializer.send
	transfer = ()
	def layer_tokens(event, layer):
		assert event == fc_initiate
		return [
			(rline, layer.initiation),
			(headers, layer.header_sequence),
			EOH,
		], layer

	def eom(event, layer):
		assert event == fc_terminate
		return (EOM,), layer

	def data(event, layer, payload, xchunk=libhttp.chunk):
		nonlocal content, chunk
		assert event == fc_transfer

		l = layer.length
		if l is None:
			raise Exception("content without chunked encoding specified or content length")

		if l >= 0:
			btype = content
		else:
			btype = chunk

		return [(btype, x) for x in payload], layer

	commands = {
		fc_initiate: layer_tokens,
		fc_terminate: eom,
		fc_transfer: data,
	}
	transformer = commands.__getitem__

	while 1:
		events = (yield transfer)
		transfer = []
		for event in events:
			out_events, layer = transformer(event[0])(*event)
			transfer.extend(serialize(out_events))

def fork(
		Layer,
		rline=libhttp.Event.rline,
		headers=libhttp.Event.headers,
		trailers=libhttp.Event.trailers,
		content=libhttp.Event.content,
		chunk=libhttp.Event.chunk,
		violation=libhttp.Event.violation,
		bypass=libhttp.Event.bypass,
		EOH=libhttp.EOH,
		EOM=libhttp.EOM,
		iter=iter, map=map, len=len,
		chain=itertools.chain.from_iterable,
		fc_initiate=libio.FlowControl.initiate,
		fc_terminate=libio.FlowControl.terminate,
		fc_transfer=libio.FlowControl.transfer,
	):
	"""
	Split an HTTP stream into flow events for use by &libio.Division.
	"""
	global libhttp

	tokenizer = libhttp.disassembly()
	tokens = tokenizer.send

	close_state = False # header Connection: close
	events = iter(())
	flow_events = []

	# Pass exception as terminal Layer context.
	def http_protocol_violation(data):
		raise Exception(data)

	while not close_state:

		lrline = []
		lheaders = []
		local_state = {
			rline: lrline.extend,
			headers: lheaders.extend,
			violation: http_protocol_violation,
		}

		headers_received = False
		while not headers_received:
			for x in events:
				local_state[x[0]](x[1])
				if x == EOH:
					headers_received = True
					break
			else:
				# need more for headers
				events = []
				y = events.extend
				for x in map(tokens, ((yield flow_events))):
					y(x)
				del y
				flow_events = []
				events = iter(events)

		# got request or status line and headers for this request
		assert len(lrline) == 3

		layer = Layer()
		layer.initiate(lrline[:3])
		layer.add_headers(lheaders)

		if layer.terminal:
			# Connection: close present.
			# generator will exit when the loop completes
			close_state = True

		flow_events.append((fc_initiate, layer))
		##
		# local_state is used as a catch all
		# if strictness is desired, it should be implemented here.

		body = []
		trailer_sequence = []
		local_state = {
			# handle both chunking and content types
			content: body.append,
			chunk: body.append,
			# extension: handle chunk extension events.
			trailers: trailer_sequence.extend,
			violation: http_protocol_violation,
		}

		try:
			body_complete = False
			while not body_complete:
				for x in events:
					if x == EOM:
						body_complete = True
						break

					# not an eof event, so extend state and process as needed
					local_state[x[0]](x[1])

					if trailer_sequence:
						layer.trailer(trailer_sequence)
					else:
						if body:
							# send the body to the connected Flow
							# the Distributing instance watches for
							# obstructions on the receiver and sends them
							# upstream, so no buffering need to occur here.
							flow_events.append((fc_transfer, layer, body))

							# empty body sequence and reconfigure its callback
							body = []
							local_state[content] = local_state[chunk] = body.append

				else:
					# need more for EOM
					events = []
					y = events.extend
					for x in map(tokens, ((yield flow_events))):
						y(x)
					flow_events = []
					events = iter(events)
				# for x in events
			# while not body_complete
		except GeneratorExit:
			raise
		else:
			flow_events.append((fc_terminate, layer))
			layer = None

	# Store overflow for next protocol.
	events = []
	y = events.extend
	while True:
		for x in map(tokens, (yield flow_events)):
			y(x)
		flow_events = ()

class Protocol(object):
	"""
	Stack object for &libio.Transports.

	[ Properties ]

	/receive_overflow
		Transfers that occurred past protocol boundaries. Used during protocol
		switching to properly maintain state.
	"""
	@classmethod
	def client(Class) -> 'Protocol':
		global Response
		return Class(Response)

	@classmethod
	def server(Class) -> 'Protocol':
		global Request
		return Class(Request)

	def terminate(self, polarity=0):
		self._termination ^= polarity
		if self._termination == -2:
			self.terminated = True

	def __init__(self, Layer:Layer, selected_version=b'HTTP/1.1'):
		global fork, join

		self.version = selected_version

		self._termination = 0
		self.terminated = False
		self.receive_overflow = []

		self.input_state = fork(Layer)
		self.fork = self.input_state.send
		self.fork(None)

		self.output_state = join()
		self.join = self.output_state.send
		self.join(None)

	def ht_transport_operations(http):
		f = (False).__bool__
		return ((http.fork, f, f), (http.join, f, f))

libio.Transports.operation_set[Protocol] = Protocol.ht_transport_operations

class Client(libio.Mitre):
	"""
	Mitre flow initiating HTTP requests for a Connection sector.
	"""
	Protocol = Protocol.client

	def __init__(self, router):
		self.m_responses = []
		self.m_requests = []
		self.m_route = router

	def process(self, events, source=None):
		"""
		Received a set of response initiations. Join with requests, and
		execute the receiver provided to &m_request.
		"""
		self.m_responses.extend(events)
		signal_count = min(len(self.m_responses), len(self.m_requests))

		reqs = self.m_requests[:signal_count]
		resp = self.m_responses[:signal_count]
		del self.m_requests[:signal_count]
		del self.m_responses[:signal_count]
		for req, res in zip(reqs, resp):
			rec = req[0]
			rec(self, req[1], *res)

	def m_request(self,
			receiver:libio.ProtocolTransactionEndpoint,
			layer:Request,
			flow:libio.Flow=None
		):
		"""
		Emit an HTTP request. The corresponding response will be joined to form a
		&ProtocolTransaction instance.

		[ Parameters ]

		/receiver
			The callback to be performed when a response for the request is received.
		/layer
			The request layer context. &Request.
		/flow
			The request body to be emittted. &None if there is no body.
		"""

		layer, connect = self.f_emit((layer,), self)[0]
		self.m_requests.append((receiver, layer))
		connect(flow)

class Server(libio.Mitre):
	"""
	Mitre managing incoming server connections for HTTP.
	"""
	Protocol = Protocol.server

	def __init__(self, ref, router):
		self.m_reference = ref
		self.m_route = router

	def process(self, events, source=None):
		"""
		Accept HTTP &Request's from the remote end and pair them with &Response's.
		"""

		global ProtocolTransaction
		global Response

		cxn = self.controller
		# Reserve response slot and acquire connect callback.
		responses = self.f_emit([Response() for i in range(len(events))], self)

		for req, res in zip(events, responses):
			px = ProtocolTransaction((
				cxn, req[0], res[0], req[1], res[1], self.m_reference
			))
			px.response.add_headers([
				(b'Date', libtime.now().select('rfc').encode('utf-8')),
			])
			if req[0].terminal:
				res[0].header_sequence.append((b'Connection', b'close'))

			self.m_route(cxn, px)
