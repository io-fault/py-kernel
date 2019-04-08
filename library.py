"""
# Processor class hierarchy for managing explicitly structured processes.

# [ Properties ]
# /ProtocolTransactionEndpoint/
	# The typing decorator that identifies receivers
	# for protocol transactions.
"""
import os
import sys
import collections
import functools
import inspect
import itertools
import traceback
import collections.abc
import typing
import codecs
import contextlib
import weakref

from ..system import execution
from ..system import thread
from ..system import files
from ..system import process

from ..internet import ri
from ..internet import host

from . import system

__shortname__ = 'libkernel'

class Lock(object):
	"""
	# Event driven lock.

	# Executes a given callback when it has been dequeued with the &release method
	# as its parameter. When &release is then called by the lock's holder, the next
	# enqueued callback is processed.
	"""
	__slots__ = ('_current', '_waiters',)

	def __init__(self, Queue = collections.deque):
		self._waiters = Queue()
		self._current = None

	def acquire(self, callback):
		"""
		# Return boolean on whether or not it was **immediately** acquired.
		"""
		self._waiters.append(callback)
		# At this point, if there is a _current,
		# it's release()'s job to notify the next
		# owner.
		if self._current is None and self._waiters[0] is callback:
			self._current = self._waiters[0]
			self._current(self.release)
			return True
		return False

	def release(self):
		"""
		# Returns boolean on whether or not the Switch was
		# released **to another controller**.
		"""
		if self._current is not None:
			if not self._waiters:
				# not locked
				return False
			self._waiters.popleft()

			if self._waiters:
				# new owner
				self._current = self._waiters[0]
				self._current(self.release)
			else:
				self._current = None
		return True

	def locked(self):
		return self._current is not None

@functools.lru_cache(32)
def endpoint(type:str, address:str, port:object):
	"""
	# Endpoint constructor for fault.io applicaitons.

	# [ Samples ]
	# /IPv4/
		# `libkernel.endpoint('ip4', '127.0.0.1', 80)`
	# /IPv6/
		# `libkernel.endpoint('ip6', '::1', 80)`
	# /Local/
		# `libkernel.endpoint('local', '/directory/path/to', 'socket_file')`
	"""

	return endpoint_classes[type](address, port)

def perspectives(resource, mro=inspect.getmro):
	"""
	# Return the stack of structures used for Resource introspection.

	# Traverses the MRO of the &resource class and executes the &structure
	# method; the corresponding class, properties, and subresources are
	# then appended to a list describing the &Resource from the perspective
	# of each class.

	# Returns `[(Class, properties, subresources), ...]`.
	"""

	l = []
	add = l.append
	covered = set()

	# start generic, and filter replays
	for Class in reversed(inspect.getmro(resource.__class__)[:-1]):
		if not hasattr(Class, 'structure') or Class.structure in covered:
			continue
		covered.add(Class.structure)

		struct = Class.structure(resource)

		if struct is None:
			continue
		else:
			add((Class, struct[0], struct[1]))

	return l

def sequence(identity, resource, perspective, traversed, depth=0):
	"""
	# Convert the structure tree of a &Resource into a sequence of tuples to be
	# formatted for display.
	"""

	if resource in traversed:
		return
	traversed.add(resource)

	yield ('resource', depth, perspective, (identity, resource))

	p = perspectives(resource)

	# Reveal properties.
	depth += 1
	for Class, properties, resources in p:
		if not properties:
			continue

		yield ('properties', depth, Class, properties)

	for Class, properties, resources in p:
		if not resources:
			continue

		for lid, subresource in resources:
			subtraversed = set(traversed)

			yield from sequence(lid, subresource, Class, subtraversed, depth=depth)

def format(identity, resource, sequenced=None, tabs="\t".__mul__):
	"""
	# Format the &Resource tree in fault.text.
	"""
	import pprint

	if sequenced is None:
		sequenced = sequence(identity, resource, None, set())

	for event in sequenced:
		type, depth, perspective, value = event

		if type == 'properties':
			for k, v in value:
				if not isinstance(k, str):
					field = repr(k)
				else:
					field = k

				if isinstance(v, str) and '\n' in v:
					string = v
					# newline triggers property indentation
					lines = string.split('\n')
					pi = tabs(depth+1)
					string = '\n' + pi + ('\n' + pi).join(lines)
				else:
					string = repr(v)
					if len(string) > 32:
						string = pprint.pformat(v, indent=0, compact=True)

				yield '%s%s: %s' %(tabs(depth), field, string)
		else:
			# resource
			lid, resource = value
			rc = resource.__class__
			if '__shortname__' in sys.modules[rc.__module__].__dict__:
				modname = sys.modules[rc.__module__].__shortname__
			else:
				modname = rc.__module__.rsplit('.', 1)[-1]
			rc_id = modname + '.' + rc.__qualname__

			if hasattr(resource, 'actuated'):
				actuated = "->" if resource.actuated else "-"
				if getattr(resource, 'terminating', None):
					terminated = "." if resource.terminating else ""
				else:
					terminated = "|" if resource.terminated else ""
				interrupted = "!" if resource.interrupted else ""
			else:
				actuated = terminated = interrupted = ""

			yield '%s%s%s%s %s [%s]' %(
				tabs(depth),
				actuated, terminated, interrupted,
				lid, rc_id,
			)

def controllers(resource):
	"""
	# Return the stack of controllers of the given &Resource. Excludes initial resource.
	"""

	stack = []
	obj = resource.controller

	while obj is not None:
		add(obj)
		obj = obj.controller

	return stack

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
		Directory containing the file system socket.
		"""

		return self[0]
	address = interface

	@property
	def port(self):
		"""
		File system socket filename.
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

class Projection(object):
	"""
	# A set of credentials and identities used by a &Sector to authorize actions by the entity.

	# [ Properties ]

	# /entity/
		# The identity of the user, person, bot, or organization that is being represented.
	# /credentials/
		# The credentials provided to authenticate the user.
	# /role/
		# An effective entity identifier; an override for entity.
	# /authorization/
		# A set of authorization tokens for the systems that are being used by the entity.
	# /device/
		# An identifier for the device that is being used to facilitate the connection.
	"""

	entity = None
	credentials = None
	role = None
	authorization = None
	device = None

	def __init__(self):
		"""
		# Projections are simple data structures and requires no initialization.
		"""

class Layer(object):
	"""
	# Base class for Layer Contexts

	# [ Properties ]
	# /(&bool)terminal/
		# Whether or not the Layer Context identifies itself as being
		# the last to occur in a connection. Protocol routers use
		# this to identify when to close input and output.

	# /(&object)context/
		# The context of the layer. In cases of protocols that support
		# multiple channels, the layer's context provides channel metadata
		# so that transaction handlers can identify its source.
	"""

	context = None

from .core import Resource, Processor, Sector, Scheduler, Recurrence
from .core import Context, Transaction, Executable
from .dispatch import Call, Coroutine, Thread, Subprocess
from .kills import Fatal

class Transport(Context):
	"""
	# Essentially, the Connection class. Transport Contexts manage the I/O
	# designated for a given Transaction sector.

	# The Transaction Context that manages the stack of protocols
	# used to facilitate arbitrary I/O streams. For application protocols,
	# this class should be subclassed to implement protocol specific features
	# and manage transport stack connectivity.

	# [ Properties ]

	# /transport_contraint/
		# Whether the transport is constrainted to `'input'` or `'output'`.
		# &None if the transport is bidirectional.
	# /transport_protocols/
		# The stack of protocols that manage the communications layers.
		# &None if the stack is not being used with the channel.
	"""

	transport_constraint = None
	transport_protocols = None

	def transport_init_protocols(self):
		"""
		# Initialize the transport stack and ready the context for
		# subsequent pushes.
		"""
		self.transport_protocols = ()

	def transport_push_protocols(self, *protocols):
		"""
		# Push a protocol layer to the stack using the &identifier
		# to select the protocol and the &implementation to select
		# a particular class.
		"""
		self.transport_protocols = self.transport_protocols + protocols

	def transport_pop_protocol(self):
		"""
		# Remove a protocol layer from the stack.
		"""
		self.transport_protocols = self.transport_protocols[:-1]

	def __init__(self, series):
		self._series = series
		self._exits = 0

	def actuate(self):
		self.init_series()

	def init_series(self):
		self.controller._flow(self._series)
		self._series[0].process(None) # fix. actuation or Flow.f_initiate()
		self._series[0].atexit(self.io_exit)
		self._series[-1].atexit(self.io_exit)

	def io_exit(self, processor):
		self._exits += 1
		if self._exits >= 2:
			self.exit()

class Accept(Transport):
	"""
	# The Transport Context used to accept sockets from listening interfaces.
	# Given a set of file descriptors associated with listening sockets,
	# the Accept Transport will create the set of flows necessary to route

	# [ Engineering ]
	# In line to replace &Network, Accept is a Transport Context that fills
	# the same role, but properly identified as a Context, not an Interface.
	# It is still not certain whether Accept should handle more than one
	# Flow. sockets://127.0.0.1:8484/tls/http
	"""

	transport_constraint = 'input'

	def actuate(self):
		self.at_funnel = Funnel()
		self.xact_dispatch(self.at_funnel)

	def at_route(self, packet,
			chain=itertools.chain.from_iterable,
		):
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

	def terminate(self):
		if not super().terminate():
			return False
		Sector.terminate(self.controller)
		self.exit()

class Timeout(Processor):
	"""
	# Processor managing an adjustable time out for a Transaction or System.

	# Primarily intended for inducing termination of inactive systems,
	# Timeout manages a scheduled event based on a configured delay,
	# and the effects for when the event occurs.
	"""

	def __init__(self, requirement, condition, effect):
		self.to_count = 0
		self.to_wait_time = requirement
		self.to_condition = condition
		self.to_effect = effect

	def actuate(self):
		self.ctx_enqueue_task(self.to_schedule)

	def terminate(self, by=None):
		"""
		# Terminate the timeout causing the effect to
		# not occur given that it hasn't already.
		"""
		if not super().terminate(by=by):
			return False
		self.controller.scheduler.cancel(self.to_execute)
		self.exit()

	def to_schedule(self):
		self.controller.scheduler.defer(self.to_wait_time, self.to_execute)

	def to_execute(self):
		assert self.functioning

		extend_time = None
		if self.to_condition:
			try:
				self.to_effect() # Timeout occurred. [Timeout Effect Faulted]
				self.ctx_enqueue_task(self.terminate)
			except BaseException as exc:
				self.fault(exc)
		else:
			# Condition not met, try timeout again later.
			self.to_schedule()

class Network(Context):
	"""
	# An Interface used to manage the set of system listening interfaces and
	# connect accept events to an appropriate controller.

	# [ Properties ]

	# /if_slot/
		# The set of interfaces that will source connections to be processed by
		# this interface.
	"""

	if_slot = None

	def structure(self):
		p = [
			('if_slot', self.if_slot),
		]
		return (p, ())

	def __init__(self, mitre, ref, router, transports, slot=None):
		"""
		# Select the &Ports slot to acquire listening sockets from.

		# [ Parameters ]

		# /slot/
			# The slot to acquire from the &Ports instance assigned to "/dev/ports".
		"""
		super().__init__()
		self.if_transports = transports
		self.if_slot = slot

		self.if_mitre = mitre
		self.if_reference = ref
		self.if_router = router

	def actuate(self):
		super().actuate()

		self.bindings = set()
		add = self.bindings.add

		ctx = self.context
		sector = self.controller
		ports = ctx.association().ports

		fds = ports.acquire(self.if_slot)

		for listen in ctx.acquire_listening_sockets(fds.values()):
			x, flow = listen
			sector.dispatch(flow)

			if_r = (x.interface, x.port)
			if_t = Sockets(if_r, self.if_spawn_connections)
			sector.dispatch(if_t)
			if_t.f_connect(null)

			flow.f_connect(if_t)

			add(if_r)
			flow.process(None) # Start allocating file descriptor arrays.

		return self

	def if_source_exhausted(self, sector):
		"""
		# Callback ran when the sockets sector exits.

		# This handles cases where all the listening sockets are closed.
		"""
		pass

	def if_spawn_connections(self, packet,
			chain=itertools.chain.from_iterable,
		):
		"""
		# Spawn connections from the socket file descriptors sent from the upstream.

		# [ Parameters ]
		# /packet/
			# The sequence of sequences containing Kernel Port references (file descriptors).
		# /transports/
			# The transport layers to configure &Transports transformers with.

		# [ Effects ]
		# Dispatches &Connection instances associated with the accepted file descriptors
		# received from the upstream.
		"""
		sector = self.controller
		ctx_accept = self.context.accept_subflows

		source, event = packet
		for fd in chain(event):
			mitre = self.if_mitre(self.if_reference, self.if_router)
			series = ctx_accept(fd, mitre, mitre.Protocol())
			cxn = Transaction.create(Transport(series))
			sector.dispatch(cxn) # actuate and assign the connection

ProtocolTransactionEndpoint = typing.Callable[[
	Processor, Layer, Layer, typing.Callable[[Processor], None]
], None]

def Encoding(
		transformer,
		encoding:str='utf-8',
		errors:str='surrogateescape',

		gid=codecs.getincrementaldecoder,
		gie=codecs.getincrementalencoder,
	):
	"""
	# Encoding Transformation Generator.
	"""

	emit = transformer.f_emit
	del transformer # don't hold direct reference, only need emit.
	escape_state = 0

	# using incremental decoder to handle partial writes.
	state = gid(encoding)(errors)
	operation = state.decode

	output = None

	input = (yield output)
	output = operation(input)
	while True:
		input = (yield output)
		output = operation(input)

def context(max_depth=None):
	"""
	# Finds the &Processor instance that caused the function to be invoked.

	# Used to discover the execution context when it wasn't explicitly
	# passed forward.
	"""

	f = sys._getframe().f_back
	while f:
		if f.f_code.co_name == '_fio_fault_trap':
			# found the _fio_fault_trap method.
			# return the processor that caused this to be executed.
			return f.f_locals['self']
		f = f.f_back

	return None # (context) Processor is not available in this stack.

def pipeline(sector, kpipeline, input=None, output=None):
	"""
	# Execute a &..system.execution.PInvocation object building an IO instance
	# from the input and output file descriptors associated with the
	# first and last processes as described by its &..system.execution.Pipeline.

	# Additionally, a mapping of standard errors will be produced.
	# Returns a tuple, `(input, output, stderrs)`.

	# Where stderrs is a sequence of file descriptors of the standard error of each process
	# participating in the pipeline.
	"""

	ctx = sector.context
	pl = kpipeline()

	try:
		input = ctx.acquire('output', pl.input)
		output = self.acquire('input', pl.output)

		stderr = list(self.acquire('input', pl.standard_errors))

		sp = Subprocess(*pl.process_identifiers)
	except:
		pl.void()
		raise

	return sp, input, output, stderr
