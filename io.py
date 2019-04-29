"""
# I/O Transaction Contexts for managing transfers and protocol transports.

# I/O is managed using three types: &Transfer, &Transport, and &Interface.
# &Transfer is the Transaction that manages the flows supporting a bidirectional or unidirecitonal
# stream.
"""
import typing
import itertools
import functools

from . import core
from . import flows

from ..internet import ri
from ..internet import host

class Transfer(core.Context):
	"""
	# Context managing a *single* sequence of &flows.Channel instances.

	# [ Properties ]
	# /io_transport/
		# The &Transport context that is directly facilitating the transfer.
		# &None if none.
	"""

	def actuate(self):
		self.provide('transfer')

	_io_start = None
	io_transport = None

	@property
	def io_complete(self) -> bool:
		return self.terminated or self.terminating

	def io_flow(self, series, Terminal=flows.Terminal) -> flows.Terminal:
		"""
		# Connect a sequence of &flows.Channel instances to a new &flows.Terminal
		# instance that signals the &Transfer when the Flow has completed.

		# The &flows.Terminal created and dispatched will be returned and the &Transfer flow
		# count will be incremented.
		"""

		assert self._io_start is None

		self._io_start = series[0]
		dispatch = self.controller.dispatch

		end = Terminal(self._io_transfer_terminated)
		for x in series:
			dispatch(x)
		dispatch(end)

		downstream = end
		for x in reversed(series):
			x.f_connect(downstream)
			downstream = x

		return end

	def io_execute(self):
		"""
		# Signal the first &flows.Channel that it should begin performing transfers.
		"""
		self._io_start.f_transfer(None)

	def _io_check_terminate(self):
		if self.xact_empty():
			self.finish_termination()
		# Dispatch timeout?

	def _io_transfer_terminated(self, terminal):
		"""
		# Count to two and exit the transaction.
		"""
		self.start_termination()
		self.enqueue(self._io_check_terminate)

class Transport(Transfer):
	"""
	# The Transaction Context that manages the stack of protocols
	# used to facilitate arbitrary I/O streams.
	"""

	def actuate(self):
		self.provide('transport')

	def __init__(self):
		self._tp_channels = {}
		self._tp_stack = []

	@classmethod
	def from_endpoint(Class, io):
		"""
		# Create and initialize an instance with the first transport layer.
		"""
		tp = Class()
		state, pair = io
		tp._tp_channels[state] = pair
		tp._tp_stack.append(state)
		return tp

	@classmethod
	def from_stack(Class, entries):
		"""
		# Create and initialize an instance with using a stack.
		"""
		tp = Class()
		return tp.tp_extend(entries)

	def tp_extend(self, entries):
		"""
		# Extend the transport stack with multiple intermediates.
		# This method should only be used prior to &tp_connect.
		"""
		channels = self._tp_channels
		stackadd = self._tp_stack.append

		for state, pair in entries:
			channels[state] = pair
			stackadd(state)

		return self

	def tp_append(self, protocol):
		"""
		# Extend the transport stack with a single intermediate.
		# This method should only be used prior to &tp_connect.
		"""
		self._tp_channels[protocol[0]] = protocol[1]
		self._tp_stack.append(protocol[0])

		return self

	def tp_connect(self, protocol, mitre):
		"""
		# Connect the given mitre series, &mitre, to the configured transport stack.
		# Usually called after dispatching an instance created with &from_stack.
		"""

		# Add protocol layer first.
		self._tp_channels[protocol[0]] = protocol[1]
		self._tp_stack.append(protocol[0])

		end = []
		start = []
		for x in self._tp_stack:
			rc, sc = self._tp_channels[x]
			end.append(sc)
			start.append(rc)

		end.reverse()
		return self.io_flow(start + [flows.Division(), mitre, flows.Catenation()] + end)

	def tp_push(self, state, io):
		"""
		# Push the protocol channels on to the stack.
		"""

		self._tp_channels[state] = io
		top = self._tp_stack[-1]
		self._tp_stack.append(state)
		dispatch = self.controller.dispatch
		top[0].f_inject(io[0])
		top[1].f_inject(io[1])
		dispatch(io[0])
		dispatch(io[1])

	def tp_protocol_terminated(self, state):
		"""
		# Called by a protocol stack entry when both sides of the state have been closed.
		"""
		pass

	def tp_remove(self, state):
		i = self._tp_stack.index(state)
		del self._tp_stack[i:i+1]
		r, s = self._tp_channels.pop(state)
		return r.p_overflow, s.p_overflow

	def tp_get(self, label):
		for i in self._tp_stack:
			l, x = i
			if label == l:
				return x, self._tp_channels[i]

		raise LookupError(label)

class Interface(core.Executable):
	"""
	# Executable context managing a logical interface.
	"""

	def if_route(self, packet, chain=itertools.chain.from_iterable):
		"""
		# Route the accepted connections.
		"""

		source, event = packet
		for io_pair in chain(event):
			self.xact_dispatch(f)

	def if_install(self, *kports):
		"""
		# Given file descriptors, install a new set of flows
		# accepting sockets from the given listening sockets.
		"""

		acquire = self.system.acquire_listening_sockets

		for listen in acquire(kports):
			x, flow = listen

			if_r = (x.interface, x.port)
			if_t.f_connect(null)

			flow.f_connect(if_t)
			flow.f_transfer(None) # Start allocating file descriptor arrays.

class Accept(Transfer):
	"""
	# The Transfer Context used to accept and route sockets from listening interfaces.

	# [ Engineering ]
	# In line to replace &Network, Accept is a Transport Context that fills
	# the same role, but properly identified as a Context, not an Interface.
	# It is still not certain whether Accept should handle more than one
	# Flow. sockets://127.0.0.1:8484/tls/http
	"""

	def at_route(self, packet, chain=itertools.chain.from_iterable):
		"""
		# Moving to Sockets. Routing will be handled with flows.
		"""
		sector = self.controller
		ctx_accept = self.context.accept_subflows

		source, event = packet
		for fd in chain(event):
			mitre = self.if_mitre(self.if_reference, self.if_router)
			series = ctx_accept(fd, mitre, mitre.Protocol())
			cxn = Transaction.create(Transport(series))
			sector.dispatch(cxn) # actuate and assign the connection

	def at_install(self, *kports):
		"""
		# Given file descriptors, install a new set of flows
		# accepting sockets from the given listening sockets.
		"""
		ctx = self.context
		sector = self.controller

		for listen in ctx.acquire_listening_sockets(kports):
			x, flow = listen
			sector.dispatch(flow)

			if_r = (x.interface, x.port)
			if_t = Sockets(if_r, self.at_route)
			sector.dispatch(if_t)
			if_t.f_connect(null)

			flow.f_connect(if_t)

			add(if_r)
			flow.process(None) # Start allocating file descriptor arrays.

	def at_bind(self, slot):
		"""
		# Bind the Kernel Ports associated with the given slot.
		# Allocates duplicate file descriptors from `/dev/ports`,
		# and installs them in the Transaction.
		"""
		ctx = self.context
		ports = ctx.association().ports

		fds = ports.acquire(self.if_slot)
		self.at_install(*fds)

def security_operations(transport):
	"""
	# Construct the input and output operations used by &.library.Transports instances.
	# All implementations accessible from &..security expose the same features,
	# so &operations is implementation independent.
	"""

	return (
		(transport.decipher, transport.pending_input, transport.pending_output),
		(transport.encipher, transport.pending_output, transport.pending_input),
	)

def dispatch(xact, *flows:typing.Sequence[flows.Channel]):
	"""
	# Dispatch a set of a flows within the Transaction as connected Transfers.
	"""

	for x in reversed(flows):
		xf = Transfer()
		sub = Transaction.create(xf)
		xact.dispatch(sub)
		xf.critical(functools.partial(xf.io_flow, *x))

class Local(tuple):
	"""
	# A reference to a unix domain file system socket.

	# While local connections do not have "addresses", &..io generalizes
	# all endpoints regardless of transport. In the case of local sockets,
	# the directory containing the socket file is known as the `address`,
	# and the filename is known as the `port`.

	# All local socket connections are said to transfer "octets" and
	# are semantically consistent with TCP/IP connections.
	"""

	__slots__ = ()

	@property
	def protocol(self):
		return 'local'

	@property
	def interface(self):
		"""
		# Directory containing the file system socket.
		"""

		return self[0]
	address = interface

	@property
	def port(self):
		"""
		# File system socket filename.
		"""

		return self[1]

	@property
	def route(self):
		return files.Path.from_absolute(self[0]) / self[1]

	@classmethod
	def create(Class, directory, file):
		return Class((directory, file))

	def __str__(self):
		return '[' + (self[0].rstrip('/') + '/') +self[1]+']'

class Endpoint(tuple):
	"""
	# A process-local endpoint. These objects are pointers to [logical] process resources.
	"""

	__slots__ = ()
	protocol = 'rs' # Process[or Unit] Space

	@property
	def unit(self):
		"""
		# The absolute unit name; &None if subjective reference.
		"""

		return self[0]

	@property
	def pid(self):
		"""
		# The process identifier pointing to the location of the endpoint.
		# Necessary in interprocess communication.
		"""

		return self[4]

	@property
	def path(self):
		"""
		# The path in the structure used to locate the container.
		"""

		if not self.directory:
			return self[1][:-1]

	@property
	def identifier(self):
		"""
		# Last component in the path if it's not a directory.
		"""

		if not self.directory:
			return self[1][-1]

	@property
	def directory(self):
		"""
		# Endpoint refers to the *directory* of the location, not the assigned object.
		"""

		return self[2]

	@property
	def validation(self):
		"""
		# A unique identifier selecting an object within the &Resource.
		# Usually the result of an &id call of a particular object
		"""

		return self[3]

	def __str__(self, formatting = "{0}{4}/{1}{2}{3}"):
		one = '/'.join(self.path)
		three = two = ''

		if self.directory:
			two = '/'
		if self.validation is not None:
			three = '#' + str(self.validation)

		if self.program:
			zero = "rs://" + self.unit
		else:
			zero = "/"

		if self.pid is not None:
			four = ":" + str(self.pid)

		return formatting.format(zero, one, two, three, four)

	@classmethod
	def parse(Class, psi):
		"""
		# Parse an IRI-like indicator for selecting a process object.
		"""

		dir = False
		d = ri.parse(psi)

		path = d.get('path', ())
		if path != ():
			if path[-1] == '':
				pseq = path[:-1]
				dir = True
			else:
				pseq = path
		else:
			pseq = ()

		port = d.get('port', None)

		return Class(
			(d['host'], tuple(pseq), dir, d.get('fragment', None), port)
		)

	@classmethod
	def local(Class, *path, directory = False):
		"""
		# Construct a local reference using the given absolute path.
		"""

		return Class((None, path, directory, None, None))

endpoint_classes = {
	'local': Local.create,
	'ip4': host.Endpoint.create_ip4,
	'ip6': host.Endpoint.create_ip6,
	'domain': host.Reference.from_domain,
}

@functools.lru_cache(32)
def endpoint(type:str, address:str, port:object):
	"""
	# Endpoint constructor for fault.io applicaitons.

	# [ Samples ]
	# /IPv4/
		# `kio.endpoint('ip4', '127.0.0.1', 80)`
	# /IPv6/
		# kio.endpoint('ip6', '::1', 80)`
	# /Local/
		# kio.endpoint('local', '/directory/path/to', 'socket_file')`
	"""

	return endpoint_classes[type](address, port)
