"""
Internet HTTP support for io applications.
"""
import functools
import collections
import itertools
import json
import pprint
import typing
import weakref

from ..computation import library as libcomp
from ..internet import libhttp
from ..internet import libmedia
from ..chronometry import library as libtime

from . import core

class Layer(core.Layer):
	"""
	The HTTP layer of a connection; superclass of &Request and &Response that provide
	access to the parameters of a &Transaction.
	"""

	protocol = 'http'
	version = 1

	@property
	def content(self):
		"Whether the Layer Context is associated with content."
		return self.length is not None

	@property
	def length(self):
		"The length of the content; positive if exact, &None if no content, and -1 if arbitrary."

		cl = self.headers.get(b'content-length')
		if cl is not None:
			return int(cl.decode('utf-8'))

		te = self.headers.get(b'transfer-encoding')
		if te is not None and te.lower().strip() == b'chunked':
			return -1

		# no content
		return None

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
	def connection(self):
		"Return the connection header stripped and lowered or &<b''> if no header present"
		return self.headers.get(b'connection', b'').strip().lower()

	@property
	def media_range(self, parse_range=libmedia.Range.from_bytes):
		"Structured form of the Accept header."

		if b'accept' in self.headers:
			return parse_range(self.headers[b'accept'])
		else:
			return libmedia.any_range

	@property
	def date(self, parse = libtime.parse_rfc1123):
		"Date header timestamp."

		if not b'date' in self.headers:
			return None

		ts = self.headers[b'date'].decode('utf-8')
		return parse(ts)

	@property
	def encoding(self):
		"Character encoding of entity content. &None if not applicable."
		pass

	@property
	def terminal(self):
		"Whether this is the last request or response in the connection."

		if self.version == b'1.0':
			return True

		return self.connection == b'close'

	@property
	def substitution(self):
		"Whether or not the request looking to perform protocol substitution."

		return self.connection == b'upgrade'

	@property
	def cookies(self):
		"Cookie sequence for retrieved Cookie headers or Set-Cookie headers."

		self.parameters.get('cookies', ())

	def __init__(self):
		self.parameters = dict()
		self.headers = dict()
		self.inititation = None
		self.header_sequence = []

	def __str__(self):
		init = " ".join(x.decode('utf-8') for x in self.initiation)
		heads = "\n\t".join(x.decode('utf-8') + ': ' + y.decode('utf-8') for (x,y) in self.header_sequence)
		return init + "\n\t" + heads

	def initiate(self, rline):
		"Called when the request or response was received from a remote endpoint."
		self.initiation = rline

	def add_headers(self, headers, cookies = False, cache = ()):
		"Accept a set of headers from the remote end."

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
		self.accept(headers)

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

	transport(events)
	del events

	try:
		if length is None:
			# transport EOM in finally
			pass
		else:
			# emit until generator is explicitly stopped
			while 1:
				transport(zip(repeat(btype), (yield)))
	finally:
		# generator exit
		transport((EOM,))

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
		chain=itertools.chain,
	):
	"""
	Generator function for maintaining the input state of a sequence of HTTP transactions.

	Given a Transaction allocation function and a Transaction completion function, receive.
	"""

	close_state = False # header Connection: close
	events = iter(())
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
				events = iter(chain(*(yield)))

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

		body = [] # XXX: context based allocation? (memory constraints)
		trailer_sequence = []
		local_state = {
			# handle both chunking and content types
			content: body.append,
			chunk: body.append,
			trailers: trailer_sequence.extend,
			violation: http_protocol_violation,
		}

		# notify the protocol that the transaction is ready
		ready(layer)

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
						# send a copy of the body onward
						transport(layer, (body,))

						body = []
						local_state[content] = local_state[chunk] = body.append

			else:
				# need more for EOM
				events = iter(chain(*(yield)))
			# for x in events
		else:
			# pop transaction
			finish(layer)
			layer = None

		# while not body_complete
	# while not close_state

	# During Protocol Substitution, the disassembler
	# may produce bypass events that contain data for
	# the protocol that is taking over the connection.
	excess = bytearray()
	while True:
		# Expecting bypass events.
		for typ, data in events:
			if typ == bypass:
				excess += data

		# XXX: currently no way to access the excess
		events = iter(chain(*(yield)))

def flows(xact, input, output):
	"""
	Construct a pair of &.library.Flow instances with the given &.library.Transformer
	instances in &input and &output as the flows' definition.
	"""
	fi, fo = xact.flows()

	fi.requisite(*input)
	fi.sequence[-1].compose(libcomp.unroll(libhttp.disassembly().send, Sequence=tuple))

	fo.requisite(*output)
	fo.sequence[0].compose(libcomp.plural(libhttp.assembly().send))

	return fi, fo

def client_v1(xact, accept, closed, input, output, transports=()):
	"""
	Given input and output Flows, construct and connect a Protocol instance
	for an HTTP 1.x client connection.
	"""

	global Response, Request, v1_input, v1_output

	fi, fo = flows(xact, input, output)
	if transports:
		# Before the Composition
		ti = fi.sequence[-2]
		# After the Composition
		to = fo.sequence[1]
		ti.requisite(to)
		to.requisite(ti)
		ti.configure(1, (transports[0],), transports[1])

	p = core.QueueProtocol(Response, Request, v1_input, v1_output)
	p.requisite(accept, closed, fi, fo)

	return p, fi, fo

def server_v1(xact, accept, closed, input, output):
	fi, fo = flows(xact, input, output)

	p = core.QueueProtocol(Request, Response, v1_input, v1_output)
	p.requisite(accept, closed, fi, fo)

	return p, fi, fo

class Interface(core.Interface):
	"""
	An HTTP interface Sector. Provides the foundations for constructing
	an HTTP 2.0, 1.1, and 1.0 interface.
	"""

class Client(core.Connection):
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

	def actuate(self):
		self.response_endpoints = []
		super().actuate()
		endpoint = self.endpoint
		transports = self.transports

		with self.xact() as xact:
			io = xact.connect(
				endpoint.protocol, endpoint.address, endpoint.port,
				transports = transports,
			)

			p, fi, fo = client_v1(xact,
				self.http_transaction_open,
				self.http_transaction_close,
				*io, transports=transports)

			self.protocol = p
			self.process((p, fi, fo))
			# start allocator.
			fi.process(None)

	def http_transaction_open(self, layer, connect):
		"""
		Notify the user of the open transaction by performing the callback
		given as the receiver parameter to &http_request.
		"""

		ep, request = self.response_endpoints[0]
		del self.response_endpoints[0]

		ep(self, request, layer, connect)

	def http_transaction_close(self, layer, flow):
		# called when the input flow of the request is closed
		# by the finish() call in the HTTP state generator.
		pass

	def http_request(self,
			receiver:core.ProtocolTransactionEndpoint,
			layer:core.Layer,
			flow:core.Flow=None
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

		self.response_endpoints.append((receiver, layer))

		out = self.protocol.serialize
		out.enqueue(layer)
		out.connect(layer, flow)

class Agent(core.Controller):
	"""
	&Client connection controller managing common resources and configuration.

	Agents provide a set of interfaces that return a &Processor representing
	the dispatched conceptual task. These conceptual tasks may be supported by
	one or more &Client instances managed by the Agent.

	[ Properties ]

	/(&str)title
		The default `User-Agent` header.
	/(&typing.Mapping)connections
		The &Client connections associated with their host.
	"""

	def __init__(self):
		super().__init__()
		self.connections = collections.defaultdict(set)

	def connect_to_file(sector, request, response, connect, transports=(), tls=None):
		with sector.allocate() as xact:
			target = xact.append(str(path))
			f = xact.flow((libio.Iterate(),), target)

		sector.dispatch(f)
		f.atexit(functools.partial(response_collected, sector, request, response))
		connect(f)

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
		Open a client connection and return the &Client instance.
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
	Used to interface with Python systems.

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

	return match, adaption

def resource(**kw):
	"""
	HTTP Resource Method Decorator

	#!/pl/python
		@http.resource(limit=0, ...)
		def method(self, sector, request, response, input):
			pass

		@method.override('text/html')
		def method(self, sector, request, response, input):
			"Resource implementation for text/html requests(Accept Header)."
			pass
	"""

	global functools, Resource
	return functools.partial(Resource, **kw)

class Resource(object):
	"""
	Decorator for trivial Python HTTP interfaces.

	Performs automatic conversion for input and output based on the Accept headers.
	"""

	def __init__(self, call, limit=None):
		self.parameters = [
			x for x in locals().items() if x[0] != 'self'
		]
		self.call = call
		self.overrides = {}
		functools.wraps(self.call)(self)

	def override(self, *types):
		"""
		Override the request handler for the resource when the request
		is preferring the given type.
		"""

		def Temporary(call):
			for x in types:
				self.overrides[libmedia.Type.from_string(x)] = call
			return self

		return Temporary

	def execution(self, sector, request, response, input, output):
		result = self.call(sector, request, response, input)

		ct, data = adapt(None, request.media_range, result)
		response.add_headers([
			(b'Content-Type', str(ct).encode('utf-8')),
			(b'Content-Length', str(len(data)).encode('utf-8')),
		])
		if request.terminal:
			response.add_headers([
				(b'Connection', b'close')
			])

		response.initiate((request.version, b'200', b'OK'))

		f = core.Flow()
		f.affix(core.Transformer())
		f.subresource(sector)
		sector.affix(f)
		output(f)

		f.process((data,))
		f.terminate(self)

	def adapt(self,
			sector, request, response, input, output,
			str=str, len=len, create_flow=core.Flow,
		):
		# input and output are callbacks that accept Flow's to connect
		# to the request's I/O

		if input is not None:
			# Buffer and transform the input to the callable.
			fi = create_flow(core.Collect.list)
			sector.dispatch(fi)
			input(fi)

			def transformed(flow, call=self.call, args=(sector,request,response)):
				store = flow.sequence[0].storage
				data_input = b''.join(store)
				call(*args)

			fi.atexit(transformed)
			return fi
		else:
			result = self.call(sector, request, response, None)

			ct, data = adapt(None, request.media_range, result)
			response.add_headers([
				(b'Content-Type', str(ct).encode('utf-8')),
				(b'Content-Length', str(len(data)).encode('utf-8')),
			])
			if request.terminal:
				response.add_headers([
					(b'Connection', b'close')
				])

			response.initiate((request.version, b'200', b'OK'))

			f = core.Flow()
			f.requisite(core.Iterate())
			f.sequence[0].requisite(terminal=True)
			sector.dispatch(f)

			# connect output and initiate the iterator
			output(f)
			f.process([(data,)])
		return f
	__call__ = adapt
