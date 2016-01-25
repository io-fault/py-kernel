"""
IETF HTTP support for &..io based applications.

&.libhttp provides support for clients and servers. The &Interface and &Host
classes provide the foundations for HTTP services. &Agent and &Client
provide the foundations for high-level HTTP clients.

In addition, &.libhttp has adapters for converting Python data structures and
interfaces into something that can be used with HTTP Interfaces and Agents.

[ Properties ]

/HeaderSequence
	Type annotation for the header sequence used by &Layer instances,
	&Layer.header_sequence.
"""
import typing
import functools
import collections
import itertools

import json
import hashlib
import operator

from ..computation import library as libc
from ..computation import libmatch
from ..chronometry import library as libtime
from ..routes import library as libroutes

from ..internet import libhttp
from ..internet import libmedia
from ..internet import libri
from ..internet.data import http as httpdata

from . import library as libio

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

	interface = property(ig(0))
	host = property(ig(1))

	# For agent transactions.
	agent = property(ig(0))
	context = property(ig(1))

	connection = property(ig(2))
	request = property(ig(3))
	response = property(ig(4))
	connect_input = property(ig(5))
	connect_output = property(ig(6))

	del ig

	def reflect(self):
		"""
		Send the input back to the output.

		Primarily used for performance testing.
		"""

		f = libio.Flow()
		self.connection.dispatch(f)
		self.connect_output(f)
		self.connect_input(f)

	def iterate_output(self, iterator):
		"""
		Construct a Flow consisting of a single &libio.Iterate instance
		used to stream output to the connection protocol state.

		The &libio.Flow will be dispatched into the &Connection for proper
		fault isolation in cases that the iterator produces an exception.
		"""
		global libio

		i = libio.Iterate(terminal=True)
		f = libio.Flow(i)
		self.connection.dispatch(f)

		self.response.initiate((self.request.version, b'200', b'OK'))
		self.connect_output(f)
		f.process(iterator)

		return f

	def read_file_into_output(self, path, range=None, str=str):
		"""
		Send the file referenced by &path to the remote end as
		the (HTTP) entity body.

		The response must be properly initialized before invoking this method.

		[ Parameters ]
		/path
			A string containing the file's path.
		/range
			The slice of the file to write.
		"""

		cxn = self.connection
		transit, = cxn.context.open_files((path,))
		f = libio.Flow(*libio.core.meter_input(libio.KernelPort(transit)))
		cxn.dispatch(f)

		self.connect_output(f)
		f.process(None)

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
		"""

		cxn = self.connection
		with cxn.allocate() as xact:
			target = xact.append(str(route))
			f = cxn.flow((libio.Iterate(),), target)

		self.connect_input(f)
		return f

	def read_input_into_file(self, route):
		"""
		Connect the input Flow's entity body to the given file.

		The file will be truncated and data will be written in append mode.
		"""

		cxn = self.connection
		with cxn.allocate() as xact:
			target = xact.append(str(route))
			f = cxn.flow((libio.Iterate(),), target)

		self.connect_input(f)
		return f

	def write_kport_to_output(self, fd, limit=None):
		"""
		Transfer data from the &kport, file descriptor to the output
		constrained by the limit.

		The file descriptor will be closed after the transfer is complete.
		"""

		cxn = self.connection
		with cxn.allocate() as xact:
			target = xact.acquire('input', fd)
			f = cxn.flow(target)

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
		with cxn.allocate() as xact:
			target = xact.acquire('output', fd)
			f = cxn.flow((libio.Iterate(),), target)

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
	"""

	protocol = 'http'
	version = 1

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
		"Return the connection header stripped and lowered or `b''` if no header present"
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
		"Structured form of the Accept header."
		return self.media_range_cache(self.headers.get(b'accept'))

	@property
	def media_type(self):
		""
		global libmedia
		return libmedia.type_from_string(self.headers[b'content-type'].decode('utf-8'))

	@property
	def date(self, parse=libtime.parse_rfc1123) -> libtime.Timestamp:
		"Date header timestamp."

		if not b'date' in self.headers:
			return None

		ts = self.headers[b'date'].decode('utf-8')
		return parse(ts)

	@property
	def host(self) -> str:
		return self.headers.get(b'host').decode('idna')

	@property
	def encoding(self) -> str:
		"Character encoding of entity content. &None if not applicable."
		pass

	@property
	def terminal(self) -> bool:
		"Whether this is the last request or response in the connection."

		if self.version == b'1.0':
			return True

		return self.connection == b'close'

	@property
	def substitution(self) -> bool:
		"Whether or not the request looking to perform protocol substitution."

		return self.connection == b'upgrade'

	@property
	def cookies(self) -> typing.Sequence:
		"Cookie sequence for retrieved Cookie headers or Set-Cookie headers."

		self.parameters.get('cookies', ())

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
	"Request portion of an HTTP transaction"

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
		"Initialize as a GET request."
		return partial(self.declare_without_content, b'GET')

	@property
	def HEAD(self, partial=functools.partial):
		"Initialize as a HEAD request."
		return partial(self.declare_without_content, b'HEAD')

	@property
	def DELETE(self, partial=functools.partial):
		"Initialize as a DELETE request."
		return partial(self.declare_without_content, b'DELETE')

	@property
	def TRACE(self, partial=functools.partial):
		"Initialize as a TRACE request."
		return partial(self.declare_without_content, b'TRACE')

	@property
	def CONNECT(self, partial=functools.partial):
		"Initialize as a CONNECT request."
		return partial(self.declare_without_content, b'CONNECT')

	@property
	def POST(self, partial=functools.partial):
		"Initialize as a POST request."
		return partial(self.declare_with_content, b'POST')

	@property
	def PUT(self, partial=functools.partial):
		"Initialize as a PUT request."
		return partial(self.declare_with_content, b'PUT')

class Response(Layer):
	"Response portion of an HTTP transaction"

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

def v1_output(
		layer, transport,
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
	):
	"""
	Generator function for maintaining the output state of a single HTTP transaction.

	The protocol will construct a new generator for every Request/Response that is
	to be emitted to the remote end. GeneratorExit is used to signal the termination
	of the message if the Transaction length is not &None.
	"""

	serializer = libhttp.assembly()
	serialize = serializer.send

	lheaders = []
	events = [
		(rline, layer.initiation),
		(headers, layer.header_sequence),
		EOH,
	]
	length = layer.length

	if length is None:
		pass
	elif length >= 0:
		btype = content
	else:
		btype = chunk

	header = serialize(events)
	transport(header)
	del events

	try:
		if length is None:
			# transport EOM in finally clause
			pass
		else:
			# emit until generator is explicitly stopped
			while 1:
				l = list(zip(repeat(btype), (yield)))
				transport(serialize(l))
	finally:
		# generator exit
		final = serialize((EOM,))
		transport(final)

def v1_input(
		allocate, ready, transport, finish,

		rline=libhttp.Event.rline,
		headers=libhttp.Event.headers,
		trailers=libhttp.Event.trailers,
		content=libhttp.Event.content,
		chunk=libhttp.Event.chunk,
		violation=libhttp.Event.violation,
		bypass=libhttp.Event.bypass,
		EOH=libhttp.EOH,
		EOM=libhttp.EOM,
		iter=iter,
		map=map,
		chain=itertools.chain.from_iterable,
	):
	"""
	Generator function for maintaining the input state of a sequence of HTTP transactions.

	Given a Transaction allocation function and a Transaction completion function, receive.
	"""

	tokenizer = libhttp.disassembly()
	tokens = tokenizer.send

	close_state = False # header Connection: close
	events = iter(())

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
				for x in map(tokens, (yield)):
					y(x)
				del y
				events = iter(events)

		# got request or status line and headers for this request
		assert len(lrline) == 3

		layer = allocate()
		layer.initiate(lrline[:3])
		layer.add_headers(lheaders)

		if layer.terminal:
			# Connection: close present.
			# generator will exit when the loop completes
			close_state = True

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

		# notify the protocol that the transaction is ready
		ready(layer)

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
							transport(layer, (body,))

							# empty body sequence and reconfigure its callback
							body = []
							local_state[content] = local_state[chunk] = body.append

				else:
					# need more for EOM
					events = []
					y = events.extend
					for x in map(tokens, (yield)):
						y(x)
					events = iter(events)
				# for x in events
			# while not body_complete
		except GeneratorExit:
			raise
		else:
			finish(layer)
			layer = None

	# while not close_state

	# During Protocol Substitution, the disassembler
	# may produce bypass events that contain data for
	# the protocol that is taking over the connection.
	excess = []
	while True:
		# Expecting bypass events.
		for typ, data in chain(map(tokens, (yield))):
			if typ == bypass:
				excess.append(data)

client = functools.partial(libio.QueueProtocol, Response, Request, v1_input, v1_output)
server = functools.partial(libio.QueueProtocol, Request, Response, v1_input, v1_output)

class Interface(libio.Interface):
	"""
	An HTTP interface Sector. Provides the foundations for constructing
	an HTTP 2.0, 1.1, and 1.0 interface.

	[ Properties ]

	/hosts
		Set of &Host instances managed and referred to by the &Interface.
	/index
		The finite map of hostnames to &Host instances.
	"""

	construct_connection_parts = staticmethod(server)

	def actuate(self):
		super().actuate()

		if self.hosts:
			self.process(self.hosts)

	primary = None
	hosts = None
	def install(self, *hosts):
		"""
		Configure the set of HTTP hosts to route connections into.
		"""

		self.index = {}
		if hosts:
			self.primary = hosts[0]
			self.hosts = set(hosts)
			for h in self.hosts:
				self.index.update(zip(h.names, itertools.repeat(h)))

	@staticmethod
	def route(context, request, connect, partial=functools.partial, tuple=tuple):
		"""
		Relocate the connection based on the initial request's data.
		"""

		cxn = context.sector
		ifs = cxn.controller
		idx = ifs.index
		host_sector = idx.get(request.host, ifs.primary)

		cxn.relocate(host_sector)
		assert cxn.controller is host_sector

		host_sector.initial(cxn, context, request, connect)

class Host(libio.Controller):
	"""
	An HTTP Host class for managing routing of service connections.

	&Host is the conceptual root for a web interface. &Interface objects
	&libio.Resource.relocate connections into the host matches.

	[ Properties ]

	/names
		The set hostnames that this host can facilitate.
		The object can be an arbitrary container in order
		to match patterns as well.

	/canonical
		The first name (&requisite.Parameters.names) given to &requisite.
		Identifies the primary name of the Host.

	/root
		The root of the host's path as a &..computation.libmatch.SubsequenceScan.
		This is the initial path of the router in order to allow "mounts"
		at arbitrary positions. Built from &requisite prefixes.

	/index
		The handler for the root path. May be &None if &root can resolve it.

	/settings
		Index of data structures used by the host as parameters to protocol
		transaction processors.
	"""

	def __init__(self, prefixes, *names):
		super().__init__()
		self.names = set(names)
		self.prefixes = prefixes
		self.root = libmatch.SubsequenceScan(prefixes.keys())
		self.index = None

		if names:
			self.canonical = names[0]
		else:
			self.canonical = None

	def structure(self):
		props = [
			('canonical', self.canonical),
			('names', self.names),
		]

		p, r = super().structure()
		return (props + list(p), r)

	def initial(self, connection, context, request, connect):
		"""
		Process the initial request of the connection.
		"""

		# overwrite default accept callback, and perform it
		accept_request = self.accept
		context.accept_event_connect(accept_request)
		accept_request(context, request, connect)

	@staticmethod
	@functools.lru_cache(64)
	def path(initial, path, len=len, tuple=tuple):
		global Path
		iparts = initial.split('/')[1:-1]
		nip = len(iparts)
		parts = tuple(path.split('/')[1:])
		return Path(Path(None, parts[:nip]), (parts[nip:]))

	@staticmethod
	@functools.lru_cache(16)
	def strcache(obj):
		return str(obj).encode('ascii')

	@staticmethod
	@functools.lru_cache(16)
	def descriptioncache(obj):
		return httpdata.code_to_names[obj].replace('_', ' ')

	@classmethod
	def options(Class, query, px):
		"""
		Handle a request for (protocol/http)`OPTIONS * HTTP/V`.

		Individual Resources may support an OPTIONS request as well.
		"""
		raise Exception("HTTP OPTIONS not implemented")

	@classmethod
	def error(Class, code, path, query, px, exc, description=None, version=b'HTTP/1.1'):
		"""
		Host error handler. By default emits an XML document with an assigned stylesheet
		that can be retrieved for formatting the error. Additional error data may by
		injected into the document in order to provide application-level error information.

		Given the details about an HTTP error message and the corresponding
		&ProtocolTransaction, emit the rendered error to the client.
		"""

		strcode = str(code)
		code_bytes = Class.strcache(code)

		if description is None:
			description = Class.descriptioncache(code_bytes)

		description_bytes = Class.strcache(description)

		px.response.initiate((version, code_bytes, description_bytes))
		px.response.add_headers([
			(b'Content-Type', b'text/plain'),
			(b'Content-Length', str(len(description_bytes)).encode('utf-8'),)
		])

		proc = libio.Flow(libio.Iterate())
		px.connection.dispatch(proc)

		px.connect_output(proc)
		proc.process([(description_bytes,)])

		# If an exception occurred, drain the output and fault the connection.
		if exc is not None:
			fo = lambda: px.connection.output.fault(exc)
			proc.drain(lambda: px.connection.output.drain(fo))
		else:
			proc.terminate()

	def route(self, px):
		"""
		Called from an I/O (normally input) event, routes the transaction
		to the processor bound to the prefix matching the request's.

		Exceptions *must* fault the Connection, and normally do if called
		from the expected mechanism.
		"""
		global Path
		global libri

		split = px.request.path.decode('utf-8').split('?', 1)
		uri_path = split[0]

		if len(split) == 2:
			query = dict(libri.parse_query(split[1]))
		else:
			query = None

		initial = self.root.get(uri_path, None)

		# No prefix match.
		if initial is None:
			if uri_path == b'*' and px.request.method == "OPTIONS":
				return self.options(query, px)
			else:
				return self.error(404, Path(None, tuple(uri_path.split('/'))), query, px, None)
		else:
			xact_processor = self.prefixes[initial]
			path = self.path(initial, uri_path)

			try:
				xact_processor(path, query, px)
			except Exception as exc:
				# The connection will be abruptly interrupted if
				# the output flow has already been connected.
				self.error(500, path, query, px, exc)

	@staticmethod
	def accept(context, request, connect_input, partial=functools.partial):
		"""
		Accept an HTTP transaction from the remote end.
		"""

		p = context.controller
		response = p.output_layer() # construct response placeholder
		out = p.sequence
		out.enqueue(response) # *reserve* spot in output queue

		if request.terminal:
			response.header_sequence.append((b'Connection', b'close'))

		connect_output = partial(out.connect, response)
		cxn = p.controller
		host = cxn.controller

		px = ProtocolTransaction((
			host.controller, host, cxn,
			request, response,
			connect_input, connect_output
		))

		host.route(px)

class Client(libio.Connection):
	"""
	Client Connection Sector representing a single client connection.

	&Client sectors manages the flows and protocol instances of a client
	connection.

	[ Properties ]

	/response_endpoints
		The callback queue that syncrhonizes the responses to their corresponding
		requests. Items are added when requests are submitted and removed when
		a response comes in.
	"""

	def manage(self):
		r = functools.partial(self.http_transaction_open, self.response_endpoints)
		super().manage(client(), r)

	def actuate(self):
		self.response_endpoints = []
		self.add = self.response_endpoints.append
		super().actuate()

	@staticmethod
	def http_transaction_open(receivers, source, layer, connect):
		receiver, request = receivers[0]
		del receivers[0]
		receiver(source, request, layer, connect)

	def http_request(self,
			receiver:libio.core.ProtocolTransactionEndpoint,
			layer:Layer,
			flow:libio.Flow=None
		):
		"""
		Emit an HTTP request.

		[ Parameters ]

		/receiver
			The callback to be performed when a response for the request is received.
		/layer
			The request layer context.
		/flow
			The request body to be emittted.
		"""

		self.add((receiver, layer))
		out = self.protocol.sequence
		out.enqueue(layer)
		out.connect(layer, flow)

class Context(libio.Controller):
	"""
	The client context for dispatching &Client connections.
	&Context provides a second level of configuration for &Agent controllers.

	A context allows a user to dispatch connections to contain the effect
	of state storage such that it can be inherited in the &Agent or simply
	forgotten when the &Context is destroyed.

	Contexts are a reasonable way to manage client masquerading.
	"""

class Agent(libio.Controller):
	"""
	&Client connection controller managing common resources and configuration.

	Agents provide a set of interfaces that return a &Processor representing
	the dispatched conceptual task. These conceptual tasks may be supported by
	one or more &Client instances managed by the Agent.

	[ Properties ]

	/(&str)`title`
		The default `User-Agent` header.

	/(&ConnectionPool)`connections`
		The &Client connections associated with their host.
	"""

	def __init__(self):
		super().__init__()
		self.connections = collections.defaultdict(set)

	@functools.lru_cache(64)
	def encoded(self, text):
		"""
		Encoded parts cache.
		"""
		return text.encode('utf-8')

	def request(self,
			version:str, method:str,
			host:str, path:str="/",
			headers:typing.Sequence=(),
			accept:str="*/*",
			agent:str=None,
			final:bool=True,
		):
		"""
		Build a &Request instance inheriting the Agent's configuration.
		Requests can be re-used given identical parameters..

		[ Parameters ]

		/final
			Whether or not the request is the final in the pipeline.
			Causes the (http)`Connection: close` header to be emitted.
		"""

		if agent is None:
			agent = self.title

		encoded = self.encoded
		req = libhttp.Request()
		req.add_headers(self.headers)
		req.add_headers(headers)

		path = path.encode('utf-8')

		req.initiate((encoded(method), path, encoded(version)))

		headers = [
			(b'User-Agent', encoded(agent)),
			(b'Accept', encoded(accept)),
		]

		if host is not None:
			headers.append((b'Host', host.encode('idna')))

		if final is True:
			headers.append((b'Connection', b'close'))

		req.add_headers(headers)
		return req

	def cache(self, target:str,
			request:Request,
			endpoint=None,
			security:str='tls',
			replace:bool=False,
		):
		"""
		Download the HTTP resource to the filesystem. If the target file exists, a HEAD
		request will be generated in order to identify if completion is possible.

		[ Parameters ]

		/replace
			Remove the target file if it exists and download the resource again.
		"""

		raise NotImplementedError("unavailable")

	def open(self, endpoint, transports=()) -> Client:
		"""
		Open a client connection and return the actuated &Client instance.
		"""
		global Client

		hc = Client.open(self, endpoint, transports=transports)
		self.connections[endpoint].add(hc)
		self.process(hc)
		return hc

# Media Support (Accept header) for Python types.

# Preferences for particular types when no accept header is given or */*
octets = (libmedia.Type.from_string(libmedia.types['data']),)
adaption_preferences = {
	str: (
		libmedia.Type.from_string('text/plain'),
		libmedia.Type.from_string(libmedia.types['data']),
		libmedia.Type.from_string(libmedia.types['json']),
	),
	bytes: octets,
	memoryview: octets,
	bytearray: octets,

	list: (
		libmedia.Type.from_string(libmedia.types['json']),
		libmedia.Type.from_string('text/plain'),
	),
	tuple: (
		libmedia.Type.from_string(libmedia.types['json']),
		libmedia.Type.from_string('text/plain'),
	),
	dict: (
		libmedia.Type.from_string(libmedia.types['json']),
		libmedia.Type.from_string('text/plain'),
	),
	None.__class__: (
		libmedia.Type.from_string(libmedia.types['json']),
	)
}
del octets

conversions = {
	'text/plain': lambda x: str(x).encode('utf-8'),
	libmedia.types['json']: lambda x: json.dumps(x).encode('utf-8'),
	libmedia.types['data']: lambda x: x,
}


def adapt(encoding_range, media_range, obj, iterating = None):
	"""
	Adapt an arbitrary Python object to the desired request type.
	Used to interface with Python interfaces.

	The &iterating parameter instructs &adapt that the &obj is an
	iterable producing instances of &iterating. For instance,
	if the iterator produces &bytes, &iterating should be set to &bytes.
	This allows &adapt to select the conversion method based on the type
	of objects being produced.

	Returns &None when there was not an acceptable response.
	"""
	if iterating is not None:
		subject_type = iterating
	else:
		subject_type = type(obj)

	types = adaption_preferences[subject_type]

	result = media_range.query(*types)
	if not result:
		return None

	matched_request, match, quality = result
	if match == libmedia.any_type:
		# determine type from obj type
		match = adaption_preferences[subject_type][0]

	if iterating:
		c = conversion[str(match)]
		adaption = b''.join(map(c, obj))
	else:
		adaption = conversions[str(match)](obj)

	return match, (adaption,)


class Resource(object):
	"""
	HTTP Resource designating &ProtocolTransaction processing for the configured MIME types.

	A Resource is a set of methods that can facilitate an HTTP request; an arbitrary handler
	for an HTTP method can be bound using the decorator syntax referencing the acceptable
	MIME type.

	Parameters are passed to the handler based on the method's signature; json data
	structures will be parsed and passed as positional and keyword parameters.
	"""

	@classmethod
	def method(Class, **kw):
		"""
		HTTP Resource Method Decorator for POST operations.

		Used to identify a method as an HTTP Resource that can
		be invoked with a &ProtocolTransaction in order
		provide a response to a client.

		#!/pl/python
			@libhttp.Resource.method(limit=0, ...)
			def method(self, resource, path, query, protoxact):
				"Primary POST implementation"
				pass

			@method.getmethod('text/html')
			def method(self, sector, request, response, input):
				"Resource implementation for text/html requests."
				pass
		"""

		global functools
		r = Class(**kw)
		return r.__methodwrapper__

	def __methodwrapper__(self, subobj):
		"Default to POST responding to any Accept."
		functools.wraps(subobj)(self)
		self.methods[b'POST'][libmedia.any_type] = subobj
		return self

	def __init__(self, limit=None):
		self.methods = collections.defaultdict(dict)
		self.limit = limit

	def getmethod(self, *types, MimeType=libmedia.Type.from_string):
		"""
		Override the request handler for the resource when the request
		is preferring one of the given types.
		"""

		def UpdateResourceGET(call, self=self):
			"Update Resource to handle GET requests for the given resource."
			GET = self.methods[b'GET']
			for x in types:
				GET[MimeType(x)] = call
			return self

		return UpdateResourceGET

	def transformed(self, context, collection, path, query, px, flow):
		"""
		Once the request entity has been buffered into the &libio.Collect,
		it can be parsed into parameters for the resource method.
		"""

		data_input = b''.join(itertools.chain(itertools.chain(*itertools.chain(*collection))))
		mtyp = px.request.media_type
		entity_body = json.loads(data_input.decode('utf-8')) # need to adapt based on type

		self.execute(context, entity_body, path, query, px)

	def execute(self, context, content, path, query, px):
		# No input to wait for, invoke the resource handler immediately.
		methods = self.methods[px.request.method]
		media_range = px.request.media_range

		if px.request.method == b'OPTIONS':
			result = self.options(context, self, content)
		else:
			mime_type = media_range.query(*methods.keys())
			if mime_type:
				result = methods[mime_type[0]](context, self, content)
			else:
				raise Exception('cant handle accept') # host.error()

		# Identify the necessary adaption for output.
		ct, data = adapt(None, media_range, result)

		px.response.add_headers([
			(b'Content-Type', str(ct).encode('utf-8')),
			(b'Content-Length', str(sum(map(len, data))).encode('utf-8')),
		])

		return px.iterate_output((data,))

	def options(self, context, content):
		"""
		Facilitate an OPTIONS request for the &Resource.
		"""
		pass

	def adapt(self,
			context:object, path:Path, query:dict, px:ProtocolTransaction,
			str=str, len=len, partial=functools.partial
		):
		"""
		Adapt a single HTTP transaction to the configured resource.
		"""

		if px.connect_input is not None:
			if False and self.limit == 0:
				# XXX: zero limit with entity body.
				px.host.error(413, path, query, px, None)
				return

			# Buffer and transform the input to the callable adherring to the limit.
			cl = libio.Collect.list()
			fi = libio.Flow(cl)
			collection = cl.storage
			px.connection.dispatch(fi)
			fi.atexit(partial(self.transformed, context, collection, path, query, px))
			px.connect_input(fi)

			return fi
		else:
			return self.execute(context, None, path, query, px)

	__call__ = adapt

class Index(Resource):
	"""
	A Resource that represents a set of Resources and the containing resource.
	"""

	@Resource.method()
	def __index__(self, resource, path, query, px):
		"List of interfaces for service management."

		return [
			name for name, method in self.__class__.__dict__.items()
			if isinstance(method, libhttp.Resource) and not name.startswith('__')
		]

	@__index__.getmethod('text/xml')
	def __index__(self, resource, query):
		"""
		Generate the index from the &Resource methods.
		"""
		xmlctx = libxml.Serialization()

		resources = [
			name for name, method in self.__class__.__dict__.items()
			if isinstance(method, libhttp.Resource) and not name.startswith('__')
		]

		xmlgen = xmlctx.root(
			'index', itertools.chain.from_iterable(
				xmlctx.element('resource', None, name=x)
				for name, rsrc in resources
			),
			namespace='https://fault.io/xml/http/resources'
		)

		return b''.join(xmlgen)

	def __resource__(self, resource, path, query, px):
		pass

	def __call__(self, path, query, px,
			partial=functools.partial, tuple=tuple, getattr=getattr
		):
		"""
		Select the command method from the given path.
		"""
		points = path.points

		if path.index:
			protocol_xact_method = functools.partial(self.__index__)
		elif points:
			protocol_xact_method = getattr(self, points[0], None)
			if protocol_xact_method is None:
				return px.host.error(404, path, query, px, None)
		else:
			return px.host.error(404, path, query, px, None)

		return protocol_xact_method(self, path, query, px)

class Methods(object):
	"""
	Collection of HTTP methods for a requested resource.
	"""

	def __call__(self, path, query, px):
		m = getattr(self, px.request.method)
		return protocol_xact_method(path, query, px)

class Dictionary(dict):
	"""
	A set of resources managed as a mapping.
	"""
	__slots__ = ()

	def __call__(self, path, query, px):
		if path.points not in self:
			px.host.error(404, path, query, px, None)
			return

		mime, data, mode = self[path.points]

		px.response.add_headers([
			(b'Content-Type', mime.encode('utf-8')),
			(b'Content-Length', str(len(data)).encode('utf-8')),
		])
		px.iterate_output([(data,)])

class FileSystem(object):
	"""
	Transaction processor providing access to a set of search paths in order
	to resolve a Resource.

	The MIME media type is identified by the file extension.
	"""

	def __init__(self, *routes):
		self.routes = routes

	def __call__(self, path, query, px):
		suffix = path.points
		for route in self.routes:
			file = route.extend(suffix)
			if file.exists():
				px.sendfile(file)
				break
		else:
			# No such resource.
			px.host.error(404, path, query, px, None)
