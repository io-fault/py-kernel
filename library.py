"""
# Processor class hierarchy for managing explicitly structured processes.

# [ Properties ]
# /ProtocolTransactionEndpoint/
	# The typing decorator that identifies receivers
	# for protocol transactions. (Such as http requests or reponses.)
"""
import os
import sys
import errno
import array
import weakref
import collections
import functools
import operator
import queue
import builtins
import inspect
import itertools
import traceback
import collections.abc
import types
import typing
import codecs
import contextlib

from ..system import execution as libexec
from ..system import thread
from ..system import files
from ..system import process

from ..routes import library as libroutes
from ..internet import ri
from ..internet import library as libnet
from ..time import library as libtime

from . import system

__shortname__ = 'libio'

#ref://reflectd.idx/index-entry?qtl=10#resolution.status.data
	#http://hostname/path/to/resource
		# qtl: Query Time Limit (seconds)
		#octets://gai.ai/domain.name?service=http&timeout|qtl=10#record-count-of-resolution

		#if://path.ri/path/to/app
		#if://machine/32:14:...:FA
		#if://v4.ip/87.34.55.1
		#if://address-space:system-ref/address
		#if://.../127/0/1
		#if://v6.ip:system-ref/::1
		#transport://octets/80
		#transport://http/host/path/to/interface
		#octets://ip/::1
		#octets://v6.ip:80/::1#fd
		#octets://v4.ip:5555/127.0.0.1#fd
		#octets://v1-2.tls/context-name#<STATUS>, context
		#octets+flows://http/?constraints config [transformation]
		#datagrams://...

		#octets://port.kernel/socket#fd
		#octets://port.kernel/input#fd
		#octets://port.kernel/output#fd

		#flows://v1-1.http/?constraints config [transformation]
		#flows://host/...

	#octets://file.kernel/input (path)
	#octets://file.kernel/output/overwrite (path)
	#octets://file.kernel/output/append (path)

def parse_transport_indicator(ti:str, port = None):
	"""
	# Parse a Transport Indicator for constructing connection templates.
	"""
	parts = ri.parse(tri)

	hn = parts['host']
	*leading, primary = hn.split('.')

	parts['category'] = primary

	# octets+flows, if any. Indicates a transition from
	# an octets stream to a set of flows.
	transitions = tuple(parts['scheme'].split('+'))
	if len(transitions) > 1:
		parts['transitions'] = transitions
	else:
		parts['transitions'] = ()

	if primary == 'index':
		# Address Resolution of some sort. Usually GetAddressInfo.
		entry = parts['path'][0]
		service = parts.get('port', port)
	elif primary == 'kernel':
		# Only one level supported. 'port' and 'file'
		kd = parts['kdomain'], = leading
		kt = parts['ktype'] = parts['path'][0]
		if kt == 'file':
			try:
				parts['kmode'] = parts['path'][1]
			except IndexError:
				parts['kmode'] = 'read'
		else:
			parts['kmode'] = None
	else:
		# version selector. Remove leading 'v' and replace '-' with '.'.
		parts['version'] = leading[-1][1:].replace('-', '.')

	return parts

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
	# /IPv4
		# `libio.endpoint('ip4', '127.0.0.1', 80)`
	# /IPv6
		# `libio.endpoint('ip6', '::1', 80)`
	# /Local
		# `libio.endpoint('local', '/directory/path/to', 'socket_file')`
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

		for identity, subresource in resources:
			subtraversed = set(traversed)

			yield from sequence(identity, subresource, Class, subtraversed, depth=depth)

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
			identity, resource = value
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

			yield '%s/%s [%s] %s%s%s' %(
				tabs(depth), identity, rc_id,
				actuated, terminated, interrupted
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

class Coprocess(tuple):
	"""
	# A reference to a coprocess interface. Used by &.libdaemon based processes
	# in order to refer to each other.

	# Used by distributed services in order to refer to custom listening interfaces.
	"""

	__slots__ = ()

	@property
	def protocol(self):
		return 'coprocess'

	@property
	def interface(self):
		"""
		Relative Process Identifier
		"""

		return self[0]

	@property
	def port(self):
		"""
		The Host header to use to connect to.
		"""

	@classmethod
	def create(Class, coprocess_id, port):
		return Class((int(coprocess_id), str(port)))

	def __str__(self):
		return "[if/" + ':'.join((self[0], self[1])) + ']'

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
	'ip4': libnet.Endpoint.create_ip4,
	'ip6': libnet.Endpoint.create_ip6,
	'domain': libnet.Reference.from_domain,
}

class Join(object):
	"""
	# An object whose purpose is to join the completion of multiple
	# processors into a single event. Joins are used to simplify coroutines
	# whose progression depends on a set of processors instead of one.

	# Joins also enable interrupts to trigger completion events so that
	# failures from unrelated Sectors can be communicated to callback.

	# [ Properties ]

	# /dependencies/
		# The original set of processors as a dictionary mapping
		# given names to the corresponding &Processor.

	# /pending/
		# The current state of pending exits that must
		# occur prior to the join-operation's completion.

	# /callback/
		# The callable that is performed after the &pending
		# set has been emptied; defined by &atexit.
	"""

	__slots__ = ('dependencies', 'pending', 'callback')

	def __init__(self, **processors):
		"""
		# Initialize the join with the given &processor set.
		"""

		self.dependencies = processors
		self.pending = set(processors.values())
		self.callback = None

	def connect(self):
		"""
		# Connect the &Processor.atexit calls of the configured
		# &dependencies to the &Join instance.
		"""

		for x in self.dependencies.values():
			x.atexit(self.exited)

		return self

	def __iter__(self, iter=iter):
		"""
		# Return an iterator to the configured dependencies.
		"""

		return iter(self.dependencies.values())

	def __getitem__(self, k):
		"""
		# Get the dependency the given identifier.
		"""

		return self.dependencies[k]

	def exited(self, processor):
		"""
		# Record the exit of the given &processor and execute
		# the &callback of the &Join if the &processor is the last
		# in the configured &pending set.
		"""

		self.pending.discard(processor)

		if not self.pending:
			# join complete
			self.pending = None

			cb = self.callback
			self.callback = None; cb(self) # clear callback to signal completion

	def atexit(self, callback):
		"""
		# Assign the callback of the &Join.

		# If the &pending set is empty, the callback will be immediately executed,
		# otherwise, overwrite the currently configured callback.

		# The &callback is executed with the &Join instance as its sole parameter.

		# [ Parameters ]

		# /callback
			# The task to perform when all the dependencies have exited.
		"""

		if self.pending is None:
			callback(self)
			return

		self.callback = callback

class ExceptionStructure(object):
	"""
	# Exception associated with an interface supporting the sequencing of processor trees.
	"""

	actuated=True
	terminated=False
	interrupted=False
	def __init__(self, identity, exception):
		self.identity = identity
		self.exception = exception

	def __getitem__(self, k):
		return (self.identity, self)[k]

	def structure(self):
		# exception reporting facility
		exc = self.exception

		formatting = traceback.format_exception(exc.__class__, exc, exc.__traceback__)
		formatting = ''.join(formatting)

		p = [
			('traceback', formatting),
		]

		return (p, ())

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
		Projections are simple data structures and requires no initialization
		parameters.
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

class Resource(object):
	"""
	# Base class for the Resource and Processor hierarchy making up a fault.io process.

	# [ Properties ]

	# /context/
		# The execution context that can be used to enqueue tasks,
		# and provides access to the root &Unit.

	# /controller/
		# The &Resource containing this &Resource.
	"""

	context = None

	def _unset_controller(self):
		return None
	controller_reference = _unset_controller
	del _unset_controller

	def _dereference_controller(self):
		return self.controller_reference()

	def _set_controller_reference(self, obj, Ref = weakref.ref):
		self.controller_reference = Ref(obj)

	controller = property(
		fget = _dereference_controller,
		fset = _set_controller_reference,
		doc = "Direct ascending resource containing this resource."
	)
	del _dereference_controller
	del _set_controller_reference

	@property
	def unit(self):
		"""
		# Return the &Unit that contains this &Resource instance.
		"""
		return self.context.association()

	@property
	def sector(self, isinstance=isinstance):
		"""
		# Identify the &Sector holding the &Resource by scanning the &controller stack.
		"""

		c = self.controller
		while c and not isinstance(c, Sector):
			c = c.controller

		return c

	def __repr__(self):
		c = self.__class__
		mn = c.__module__.rsplit('.', 1)[-1]
		qn = c.__qualname__

		return '<%s.%s at %s>' %(
			mn, qn, hex(id(self))
		)

	def subresource(self, ascent:'Resource', Ref=weakref.ref):
		"""
		# Assign &ascent as the controller of &self and inherit its &Context.
		"""

		self.controller_reference = Ref(ascent)
		self.context = ascent.context

	def relocate(self, ascent):
		"""
		# Relocate the Resource into the &ascent Resource.

		# Primarily used to relocate &Processors from one sector into another.
		# Controller resources may not support move operations; the origin
		# location must support the erase method and the destination must
		# support the acquire method.
		"""

		controller = self.controller
		ascent.acquire(self)
		controller.eject(self)

	def structure(self):
		"""
		# Returns a pair, a list of properties and list of subresources.
		# Each list contains pairs designating the name of the property
		# or resource and the object itself.

		# The structure method is used for introspective purposes and each
		# implementation in the class hierarchy will be called (&sequence) in order
		# to acquire a reasonable representation of the Resource's contents.

		# Implementations are used by &format and &sequence.
		"""

		return None

class Device(Resource):
	"""
	# A resource that is loaded by &Unit instances into (io.resource)`/dev`

	# Devices often have special purposes that regular &Resource instances do not
	# normally fulfill. The name is a metaphor for operating system kernel devices
	# as they are often associated with kernel features.
	"""

	@classmethod
	def connect(Class, unit):
		"""
		# Load an instance of the &Device into the given &unit.
		"""

		dev = Class()
		unit.place(dev, 'dev', Class.device_entry)
		dev.subresource(unit)

		return dev

@collections.abc.Awaitable.register
class Processor(Resource):
	"""
	# A resource that maintains an abstract computational state. Processors are
	# awaitable and can be used by coroutines. The product assigned to the
	# Processor is the object by await.

	# Processor resources essentially manage state machines and provide an
	# abstraction for initial and terminal states that are often used.

	# State Transition Sequence.

		# # Instantiated
		# # Actuated
		# # Functioning
		# # Terminating
		# # Terminated

	# Where the functioning state designates that the implementation specific state
	# has been engaged. Often, actuation and termination intersect with implementation states.

	# The interrupted state is special; its used as a frozen state of the machine and is normally
	# associated with an exception. The term interrupt is used as it is nearly analogous with UNIX
	# process interrupts (unix.signal)`SIGINT`.

	# [ Properties ]
	# /terminating/
		# Whether the Processor is in a termination state. &None if
		# the Processor was never terminating.

	# [ Engineering ]
	# The Processor state is managed using a set of booleans. Considering the
	# number of processors that will be present in any complex system, condensing
	# the storage requirements by using a bitmask would help reduce the memory
	# footprint.
	"""

	_pexe_state = 0 # defaults to "object initialized"
	_pexe_states = (
		('initialized', 0), # Created.
		('actuated', 1), # Placed in Execution Context and started.
		('terminating', 2), # Received and accepted termination request.
		('terminated', -1), # Termination completed and the processor will exit().
		('deallocating', 0), # Unused state.
	)

	@property
	def actuated(self) -> bool:
		return self._pexe_state != 0

	@property
	def terminating(self) -> bool:
		return self._pexe_state == 2

	@property
	def terminated(self) -> bool:
		return self._pexe_state == -1

	@property
	def status(self, _states={k:v for v,k in _pexe_states}):
		return _states[self._pexe_state]

	def termination_started(self):
		self._pexe_state = 2

	def termination_completed(self):
		self._pexe_state = -1

	@property
	def interrupted(self) -> typing.Union[bool]:
		if self.controller:
			return self.controller.interrupted
		else:
			# No controller.
			return None

	# Origin of the interrupt or terminate
	terminator = None

	product = None
	exceptions = None

	# Only used by processor groupings.
	exit_event_connections = None

	@property
	def functioning(self):
		"""
		# Whether or not the Processor is functioning.
		# Indicates that the processor was actuated and is neither terminated nor interrupted.

		# ! NOTE:
			# Processors are functioning *during* termination; instances where
			# `Processor.terminating == True`.
			# Termination may cause limited access to functionality, but
			# are still considered functional.
		"""

		return self._pexe_state > 0 and not self.interrupted

	def controlled(self, subprocessor):
		"""
		# Whether or not the given &Processor is directly controlled by &self.
		"""

		# Generic Processor has no knowledge of subresources.
		return False

	def actuate(self):
		"""
		# Initialize the Processor for use within the controlling Sector.
		"""
		pass

	def process(self, event):
		"""
		# Processing entry point for performing work of primary interest.
		"""

		pass

	def terminate(self, by=None):
		"""
		# Request that the Processor terminate.
		# Causes the Processor to progress into a `'terminating'` or `'terminated'` state
		# given that the Processor allows it.

		# Processors that do not support direct termination requests should document why
		# in their documentation strings.
		"""

		if not self.functioning or self.terminating:
			return False

		self.termination_started()
		self.terminator = by
		return True

	def interrupt(self, context=None):
		"""
		# Signal the Processor that the controlling Sector has been interrupted,
		# and all processing of events should cease immediately.

		# Subclasses that need to perform disconnects or cancellations should
		# implement this method in order to ensure that event processing stops.
		# However, interrupt procedures will automatically rewrite the &process
		# method to perform a no-op if invoked, so carefully written subclasses
		# may not have to perform any tasks at all.
		"""

		pass

	def fault(self, exception, association=None):
		"""
		# Note the given exception as an error on the &Processor.
		# Exceptions identified as errors cause the &Processor to exit.

		# Called internally when a task associated with a Processor raises
		# an exception. The controlling Sector will be interrupted and the
		# faulting Processor identified for subsequent scrutiny.
		"""

		if self.exceptions is None:
			self.exceptions = set()

		self.exceptions.add((association, exception))
		self.exit = (lambda x: x)
		self.context.faulted(self)

	def _fio_fault_trap(self, trapped_task):
		try:
			trapped_task() # Executed relative to &Sector instance.
		except BaseException as exc:
			self.fault(exc)

	def ctx_enqueue_task(self, task, partial=functools.partial, trap=_fio_fault_trap):
		"""
		# Enqueue a task associated with the sector so that exceptions cause the sector to
		# fault. This is the appropriate way for &Processor instances controlled by a sector
		# to sequence processing.
		"""
		self.context.enqueue(partial(trap, self, task))
	del _fio_fault_trap

	def exit(self):
		"""
		# Exit the processor by signalling the controlling processor that termination
		# has completed.
		"""
		self._pexe_state = -1
		return self.controller.exited(self)

	def atexit(self, exit_callback):
		"""
		# Register a callback to be executed when the Processor has been unlinked from
		# the Resource hierarchy.

		# The given callback is called after termination is complete and the Processor's
		# reference has been released by the controller. However, the controller backref
		# should still be available at this time.

		# The callback is registered on the *controlling resource* which must be a &Processor.

		# The &exit_callback will **not** be called if the &Processor was interrupted.
		"""

		if self.terminated:
			exit_callback(self) # Processor already exited.
		else:
			self.controller.exit_event_connect(self, exit_callback)

	def final(self):
		"""
		# Identify the &Processor as being final in that the exit of the processor
		# causes the sector to *terminate*. The &Sector will, in turn, invoke termination
		# on the remaining processors and exit when all of the processors have exited.
		"""
		self.controller.final = self
		self.atexit(lambda final: final.controller.terminate())

	def __await__(self):
		"""
		# Coroutine interface support. Await the exit of the processor.
		# Awaiting the exit of a processor will never raise exceptions with
		# exception to internal (Python) errors. This is one of the notable
		# contrasts between Python's builtin Futures and fault.io Processors.
		"""

		# Never signalled.
		if not self.terminated:
			yield self
		return self.product

	def exit_event_connect(self, processor, callback, dict=dict):
		"""
		# Connect the given callback to the exit of the given processor.
		# The &processor must be controlled by &self and any necessary
		# data structures will be initialized.
		"""

		assert processor.controller is self

		eec = self.exit_event_connections
		if eec is None:
			eec = self.exit_event_connections = dict()

		cbl = eec.get(processor, ())
		eec[processor] = cbl + (callback,)

	def exit_event_disconnect(self, processor, callback):
		"""
		# Remove the callback from the set of listeners.
		"""
		l = list(self.exit_event_connections[processor])
		l.remove(callback)
		if not l:
			del self.exit_event_connections[processor]
		else:
			self.exit_event_connections[processor] = tuple(l)

	def exit_event_emit(self, processor, partial=functools.partial):
		"""
		# Called when an exit occurs to emit exit events to any connected callbacks.
		"""

		eec = self.exit_event_connections
		if eec is not None:
			self.context.enqueue(*[partial(x, processor) for x in eec.pop(processor, ())])
			if not eec:
				del self.exit_event_connections

	def structure(self):
		"""
		# Provides the structure stack with at-exit callbacks.
		"""

		props = []
		sr = ()

		if self.exit_event_connections is not None:
			props.append(('exit_event_connections', self.exit_event_connections))

		if self.product is not None:
			props.append(('product', self.product))

		if self.exceptions is not None:
			props.append(('exceptions', len(self.exceptions)))
			sr = [(ident, ExceptionStructure(ident, exc)) for ident, exc in self.exceptions]

		p = [
			x for x in [
				('terminator', self.terminator),
			] if x[1] is not None
		]
		props.extend(p)

		return (props, sr)

	def placement(self):
		"""
		# Define the set index to use when dispatched by a &Sector.

		# By default, &Sector instances place &Processor instances into
		# &set objects that stored inside a dictionary. The index used
		# for placement is allowed to be overridden in order to optimize
		# the groups and allow better runtime introspection.
		"""

		return self.__class__

	def substitute(self, processor):
		"""
		# Terminate the processor &self, but reassign the exit hooks to be performed
		# when the given &processor exits. &processor will be dispatched into the controlling
		# sector.
		"""

		raise NotImplemented

class Fatal(Processor):
	"""
	# A Processor that faults the controlling Sector upon actuation.
	"""

	@classmethod
	def inject(Class, sector, event):
		fp = Fatal()
		sector.dispatch(fp)

	def actuate(self):
		self.ctx_enqueue_task(functools.partial(self.process, None))

	def process(self, event):
		raise Exception(event)

class Call(Processor):
	"""
	# A single call represented as a Processor.

	# The callable is executed by process and signals its exit after completion.

	# Used as an abstraction to explicit enqueues, and trigger faults in Sectors.
	"""

	@classmethod
	def partial(Class, call:collections.abc.Callable, *args, **kw):
		"""
		# Create a call applying the arguments to the callable upon actuation.
		# The positional arguments will follow the &Sector instance passed as
		# the first argument.
		"""
		return Class(functools.partial(call, *args, **kw))

	def __init__(self, call:functools.partial):
		"""
		# The partial application to the callable to perform.
		# Usually, instantiating from &partial is preferrable;
		# however, given the presence of a &functools.partial instance,
		# direct initialization is better.

		# [ Parameters ]
		# /call
			# The callable to enqueue during actuation of the &Processor.
		"""
		self.source = call

	def actuate(self):
		self.ctx_enqueue_task(self.execution)

	def execution(self, event=None, source=None):
		assert self.functioning

		try:
			self.product = self.source() # Execute Callable.
			self.termination_completed()
			self.exit()
		except BaseException as exc:
			self.product = None
			self.fault(exc)

	def structure(self):
		return ([('source', self.source)], ())

class Coroutine(Processor):
	"""
	# Processor for coroutines.

	# Manages the generator state in order to signal the containing &Sector of its
	# exit. Generator coroutines are the common method for serializing the dispatch of
	# work to relevant &Sector instances.
	"""

	def __init__(self, coroutine):
		self.source = coroutine

	@property
	def state(self):
		return self.unit.stacks[self]

	def _co_complete(self):
		super().terminate()
		self.controller.exited(self)

	@types.coroutine
	def container(self):
		"""
		# ! INTERNAL:
			# Private Method.

		# Container for the coroutine's execution in order
		# to map completion to processor exit.
		"""
		try:
			yield None
			self.product = (yield from self.source)
			self.enqueue(self._co_complete)
		except BaseException as exc:
			self.product = None
			self.fault(exc)

	def actuate(self, partial=functools.partial):
		"""
		# Start the coroutine.
		"""

		state = self.container()
		self.unit.stacks[self] = state

		self.enqueue(state.send)

	def terminate(self):
		"""
		# Force the coroutine to close.
		"""
		if not super().terminate():
			return False
		self.state.close()
		return True

	def interrupt(self):
		self.state.throw(KeyboardInterrupt)

class Unit(Processor):
	"""
	# An asynchronous logical process. Unit instances are the root level objects
	# associated with the &Process instance. There can be a set of &Unit instances
	# per process, but usually only one exists.

	# Units differ from most &Processor classes as it provides some additional
	# interfaces for managing exit codes and assigned standard I/O interfaces
	# provided as part of the system process.

	# Units are constructed from a set of roots that build out the &Sector instances
	# within the runtime tree which looks similar to an in memory filesystem.
	"""

	@staticmethod
	def _connect_subflows(mitre, transit, *protocols):
		kin = KInput(transit[0])
		kout = KOutput(transit[1])

		ti, to = Transports.create(protocols)
		co = Catenation()
		di = Division()

		return (kin, ti, di, mitre, co, to, kout) # _flow input

	@staticmethod
	def _listen(transit):
		return KInput.sockets(transit)

	@staticmethod
	def _input(transit):
		return KInput(transit)
		kin = KernelPort(transit)
		fi = Transformation(*meter_input(kin))

		return fi

	@staticmethod
	def _output(transit):
		return KOutput(transit)

	@property
	def ports(self):
		"""
		# (io.location)`/dev/ports` accessor
		"""

		return self.u_index[('dev','ports')]

	@property
	def scheduler(self):
		"""
		# (io.location)`/dev/scheduler` accessor
		"""

		return self.u_index[('dev','scheduler')]

	def load_ports_device(self):
		"""
		# Load the &Ports 'device'. Usually used by daemon processes.
		"""

		ports = Ports()
		self.place(ports, 'dev', 'ports')
		ports.subresource(self)

	def device(self, entry:str):
		"""
		# Return the device resource placed at the given &entry.
		"""

		return self.u_index.get(('dev', entry))

	@property
	def faults(self):
		"""
		# The (rt:path)`/dev/faults` resource.
		"""
		return self.device('faults')

	def faulted(self, resource:Resource, path=None) -> None:
		"""
		# Place the sector into the faults directory using the hex identifier
		# as its name.

		# If the path, a sequence of strings, is provided, qualify the identity
		# with the string representation of the path, `'/'.join(path)`.
		"""

		faultor = resource.sector
		if faultor is None:
			# Resource does not have a sector or is a root Processor
			# in the Unit.
			faultor = resource
			path = self.u_reverse_index.get(faultor)

		if path is not None:
			self.place(faultor, 'faults', '/'+'/'.join(path)+'@'+hex(id(faultor)))
		else:
			self.place(faultor, 'faults', hex(id(faultor)))

		if faultor.interrupted:
			# assume that the existing interruption
			# has already managed the exit.
			pass
		else:
			faultor.interrupt()
			if not faultor.terminated:
				# It wasn't interrupted and it wasn't terminated,
				# so it should be safe to signal its exit.
				faultor.controller.exited(faultor)

	def structure(self):
		index = [('/'.join(k), v) for k, v in self.u_index.items() if v is not None]
		index.sort(key=lambda x: x[0])

		sr = []
		p = []

		for entry in index:
			if entry[0].startswith('dev/') or isinstance(entry[1], Resource):
				sr.append(entry)
			else:
				# proeprty
				p.append(entry)

		return (p, sr)

	def dispatch(self, path, processor):
		processor.subresource(self)
		self.place(processor, *path)
		try:
			processor.actuate()
			processor._pexe_state = 1
		except:
			raise

	def __init__(self):
		"""
		# Initialze the &Unit instance with the an empty hierarchy.

		# &Unit instances maintain state and it is inappropriate to call
		# the initialization function during its use. New instances should
		# always be created.
		"""
		super().__init__()

		self.identity = self.identifier = None
		self.u_exit = set()
		self.u_faults = dict()

		# total index; tuple -> sector
		self.u_index = dict()
		self.u_reverse_index = dict()

		self.u_roots = []

		# tree containing sectors; navigation access
		self.u_hierarchy = dict(
			bin = dict(), # Sectors that determine Unit's continuation
			libexec = dict(),
			etc = dict(),
			dev = dict(faults=self.u_faults),
			faults = self.u_faults,
		)

		self.u_index[('dev',)] = None
		self.u_index[('dev', 'faults',)] = None
		self.u_index[('faults',)] = None

		self.u_index[('bin',)] = None
		self.u_index[('etc',)] = None
		self.u_index[('lib',)] = None
		self.u_index[('libexec',)] = None

	def requisite(self,
			identity:collections.abc.Hashable,
			roots:typing.Sequence[typing.Callable],
			process=None, context=None, Context=None
		):
		"""
		# Ran to finish &Unit initialization; extends the sequences of roots used
		# to initialize the root sectors.
		"""

		self.identity = identity

		# Create the context for base system interfaces.
		if context is None:
			api = (self._connect_subflows, self._input, self._output, self._listen)
			context = Context(process, *api)
			context.associate(self)

			# References to context exist on every &Processor instance,
			# inherited from their controller.
			self.context = context

		self.u_roots.extend(roots)

	def atexit(self, callback):
		"""
		# Add a callback to be executed *prior* to the Unit exiting.
		"""
		self.u_exit.add(callback)

	def exited(self, processor:Processor):
		"""
		# Processor exit handler. Register faults and check for &Unit exit condition.
		"""

		addr = self.u_reverse_index.pop(processor)
		del self.u_index[addr]

		p = self.u_hierarchy
		for x in addr[:-1]:
			p = p[x]
		del p[addr[-1]]

		if processor.exceptions:
			# Redundant with Sector.exited
			# But special for Unit exits as we have the address
			self.faulted(processor, path = addr)

		if addr[0] == 'bin' and not self.u_hierarchy['bin']:
			# Exit condition, /bin/* is empty. Check for Unit control callback.
			exits = self.u_exit
			if exits:
				for unit_exit_cb in exits:
					status = unit_exit_cb(self)
					if status in (None, bool(status)):
						# callbacks are allowed to remain
						# in order to allow /control to
						# restart the process if so desired.
						exits.discard(unit_exit_cb)

			if not exits:
				ctl = self.u_index.get(('control',))
				if ctl:
					ctl.atexit(self.terminate)
					ctl.terminate()
				else:
					# Unit has no more executables, and there
					# are no more remaining, so terminate.
					self.context.process.enqueue(self.terminate)

	def actuate(self):
		"""
		# Execute the Unit by enqueueing the initialization functions.

		# This should only be called by the controller of the program.
		# Normally, it is called automatically when the program is loaded by the process.
		"""

		self._pexe_state = 1

		# Allows the roots to perform scheduling.
		scheduler = Scheduler()
		scheduler.subresource(self)
		self.place(scheduler, 'dev', 'scheduler')
		scheduler.actuate()
		scheduler._pexe_state = 1

		self.place(self.context.process, 'dev', 'process')

		for sector_init in self.u_roots:
			sector_init(self)

	def terminate(self):
		if self.terminated is not True:
			if self.context.process.primary() is self:
				if self.u_hierarchy['faults']:
					self.context.process.report()
				self.context.process.terminate(getattr(self, 'result', 0))
				self._pexe_state = -1
			else:
				self._pexe_state = -1

	def place(self, obj:collections.abc.Hashable, *destination):
		"""
		# Place the given resource in the process unit at the specified location.
		"""

		self.u_index[destination] = obj

		try:
			# build out path
			p = self.u_hierarchy
			for x in destination:
				if x in p:
					p = p[x]
				else:
					p[x] = dict()

			if destination[0] != 'faults':
				# Don't place into reverse index.
				self.u_reverse_index[obj] = destination
		except:
			del self.u_index[destination]
			raise

	def delete(self, *address):
		"""
		# Remove a &Sector from the index and tree.
		"""

		obj = self.u_index[address]
		del self.u_reverse_index[obj]
		del self.u_index[address]

	def listdir(self, *address, list=list):
		"""
		# List the contents of an address.
		# This only includes subdirectories.
		"""

		p = self.u_hierarchy
		for x in address:
			if x in p:
				p = p[x]
			else:
				break
		else:
			return list(p.keys())

		# no directory
		return None

	def report(self, target=sys.stderr):
		"""
		# Send an overview of the logical process state to the given target.
		"""

		target.writelines(x+'\n' for x in format(self.identity, self))
		target.write('\n')
		target.flush()

class Sector(Processor):
	"""
	# A processing sector; manages a set of &Processor resources according to their class.
	# Termination of a &Sector is solely dependent whether or not there are any
	# &Processor instances within the &Sector.

	# Sectors are the primary &Processor class and have protocols for managing projections
	# of entities (users) and their authorizing credentials.

	# [ Properties ]

	# /processors/
		# A divided set of abstract processors currently running within a sector.
		# The sets are divided by their type inside a &collections.defaultdict.

	# /scheduler/
		# The Sector local schduler instance for managing recurrences and alarms
		# configured by subresources. The exit of the Sector causes scheduled
		# events to be dismissed.

	# /exits/
		# Set of Processors that are currently exiting.
		# &None if nothing is currently exiting.
	"""

	scheduler = None
	exits = None
	processors = None
	product = None
	interrupted = False

	def structure(self):
		p = ()

		sr = [
			(hex(id(x)), x)
			for x in itertools.chain.from_iterable(self.processors.values())
		]

		return (p, sr)

	def __init__(self, *processors, Processors=functools.partial(collections.defaultdict,set)):
		sprocs = self.processors = Processors()
		for proc in processors:
			sprocs[proc.placement()].add(proc)

	def actuate(self):
		"""
		# Actuate the Sector by actuating its processors.
		# There is no guarantee to the order in which the controlled
		# processors are actuated.

		# Exceptions that occur during actuation fault the Sector causing
		# the *controlling sector* to exit. If faults should not cause
		# the parent to be interrupted, they *must* be dispatched after
		# &self has been actuated.
		"""

		try:
			for Class, sset in list(self.processors.items()):
				for proc in sset:
					proc.subresource(self)
					proc.actuate()
					proc._pexe_state = 1
		except BaseException as exc:
			self.fault(exc)

		return super().actuate()

	def scheduling(self):
		"""
		# Initialize the &scheduler for the &Sector.
		"""
		sched = self.scheduler = Scheduler()
		sched.subresource(self)
		sched.actuate()
		sched._pexe_state = 1

	def eject(self, processor):
		"""
		# Remove the processor from the Sector without performing termination.
		# Used by &Resource.relocate.
		"""

		self.processors[processor.__class__].discard(processor)

	def acquire(self, processor):
		"""
		# Add a process to the Sector; the processor is assumed to have been actuated.
		"""

		processor.subresource(self)
		self.processors[processor.__class__].add(processor)

	def process(self, events):
		"""
		# Load the sequence of &Processor instances into the Sector and actuate them.
		"""

		structs = self.processors

		for ps in events:
			ps.subresource(self)
			structs[ps.__class__].add(ps)
			ps.actuate()
			ps._pexe_state = 1

	_sector_terminated = Processor.exit

	def terminate(self, by=None):
		if not super().terminate(by=by):
			return False

		if self.processors:
			# Rely on self.reap() to finish termination.
			for Class, sset in self.processors.items():
				for x in sset:
					x.terminate()
		else:
			# Nothing to wait for.
			self._sector_terminated()

		return True

	def interrupt(self, by=None):
		"""
		# Interrupt the Sector by interrupting all of the subprocessors.
		# The order of interruption is random, and *should* be insignificant.
		"""

		if self.interrupted:
			return

		self.interrupted = True
		self.interruptor = by

		if self.scheduler is not None:
			self.scheduler.interrupt()

		# Sectors set if they've been interrupted, so the
		# following general case will be no-ops.
		for sector in self.processors[Sector]:
			sector.interrupt()

		for Class, processor_set in self.processors.items():
			for processor in processor_set:
				processor.interrupt() # Class

		# exits are managed by the invoker

	def exited(self, processor, set=set):
		"""
		# Sector structure exit handler.

		# Called when a Processor has reached termination and should no longer
		# be contained within the Sector.
		"""

		if self.exits is None:
			self.exits = set()
			self.ctx_enqueue_task(self.reap)

		self.exits.add(processor)

	def dispatch(self, processor:Processor):
		"""
		# Dispatch the given &processor inside the Sector.
		# Assigns the processor as a subresource of the
		# instance, affixes it, and actuates it.

		# Returns the result of actuation, the &processor.
		"""

		processor.subresource(self)
		self.processors[processor.placement()].add(processor)
		processor.actuate()
		processor._pexe_state = 1

		return processor

	def coroutine(self, gf):
		"""
		# Dispatches an arbitrary coroutine returning function as a &Coroutine instance.
		"""

		gc = Coroutine.from_callable(gf)
		self.processors[Coroutine].add(gc)
		gc.subresource(self)

		return gc.actuate()

	def _flow(self, series):
		# XXX: Replace .flow() or create a more stable access point. (implicit or explicit)
		self.process(series)

		x = series[0]
		for n in series[1:]:
			x.f_connect(n)
			x = n

	def reap(self, set=set):
		"""
		# Empty the exit set and check for sector completion.
		"""

		exits = self.exits
		if exits is None:
			# Warning about reap with no exits.
			return
		del self.exits

		struct = self.processors
		classes = set()

		for x in exits:
			struct[x.__class__].discard(x)
			self.exit_event_emit(x)
			classes.add(x.__class__)

		for c in classes:
			if not struct[c]:
				del struct[c]

		# Check for completion.
		self.reaped()

	def reaped(self):
		"""
		# Called once the set of exited processors has been reaped
		# in order to identify if the Sector should notify the
		# controlling Sector of an exit event..
		"""

		# reap/reaped is not used in cases of interrupts.
		if not self.processors and not self.interrupted:
			# no processors remain; exit Sector

			if self.scheduler is not None:
				# After termination has been completed, the scheduler can be stopped.
				#
				# The termination process is an arbitrary period of time
				# that may rely on the scheduler, so it is important
				# that this is performed here.
				self.scheduler.interrupt()

			self._sector_terminated()

	def placement(self):
		"""
		# Use &Interface.if_sector_placement if the sector has an Interface.
		# Otherwise, &Sector.
		"""

		for if_proc in self.processors.get(Interface, ()):
			# Use the interface processor's definition if any.
			return if_proc.sector_placement()
		else:
			return self.__class__

class Context(Processor):
	"""
	# The base class for &Transaction Context processors.

	# Subclasses define the initialization process of a Transaction
	# and the structures used to provide depending processors with the
	# necessary information for performing their tasks.

	# [ Namespaces ]
	# Context Processors employ two hard namespaces in its methods.
	# The `xact_ctx_` and the `xact_`. Methods and properties
	# that exist under `xact_ctx_` refer to generic Context operations
	# whereas `xact_` refers to operations that primary effect the
	# &Transaction sector containing the context.

	# [ Properties ]

	# /(&dict)xact_ctx_events/
		# Storage for initialization event completion, and
		# general storage area for the controlling &Transaction.

	# /(&bool)xact_ctx_private/
		# Whether the initialized Transaction is directly managing transactions
		# created from uncontrolled sources.
		# &None means that context privacy is irrelevant.
	"""

	xact_ctx_private = None
	xact_ctx_events = None

	@property
	def xact_ctx_contexts(self) -> 'Context':
		"""
		# The complete context of the &Transaction.
		# Ascends the controllers yielding their &Context instances until
		# the controller is no longer a Transaction.
		"""
		s = self.controller

		while isinstance(s, Transaction):
			s = s.controller
			yield s.xact_context

	def xact_dispatch(self, processor:Processor):
		"""
		# Dispatch the given &processor into the &Transaction.
		"""
		return self.controller.dispatch(processor)

	def xact_ctx_init(self, events:set):
		"""
		# Initiailze the set of events that are necessary for initialization to be complete.
		"""
		self.xact_ctx_events = {k:None for k in events}

	def process(self, *events):
		"""
		# Note the event with its associated value and terminate initialization
		# if no further events are needed.
		"""

		if self.xact_ctx_events is None:
			self.xact_ctx_events = {}

		self.xact_ctx_events.update(events)

		if None not in set(self.xact_ctx_events.values()):
			self.terminate()

class Transaction(Sector):
	"""
	# A &Sector that manages the processing of a conceptual transaction.

	# Usually found inside a &System instance's processor set,
	# these Sectors are used and subclassed to clarify the purpose of the Sector.

	# Transactions are sectors with a single &Context instance that is used to manage
	# the state of the Sector. Regular Sectors exit when all the processors are shutdown,
	# and Transactions do too. However, when termination is request of the Transaction,
	# the request is dispatched to the Context in order to make sure that events are
	# properly sequenced. Essentially, Sectors can be thought of as anonymous Transactions,
	# as opposed to defining Transactions in terms of a Sector.

	# [ Properties ]

	# /(&Context)xact_context/
		# The Processor that will be dispatched to initialize the Transaction
		# Sector and control its effect.
	"""

	@classmethod
	def create(Class, xc:Context):
		"""
		# Create a &Transaction sector with the given &Context initializaed
		# as the first Processor to be actuated.

		# This is the appropriate way to instantiate &Transaction instances
		"""

		xact = Class(xc)
		xact.xact_context = xc

		return xact

	def terminate(self, by=None):
		"""
		# Invoke the &Context.terminate method of the &xact_context property.
		# The termination of the Transaction is managed entirely by the Context.
		"""

		return self.xact_context.terminate(by=by)

class System(Transaction):
	"""
	# A Sector that is identified as an independent system providing access to functionality
	# using a set of &Interface instances.

	# Systems are distinct from &Sector instances most notably in that a System will usually
	# exit from an explicit terminate or a fault. Sectors naturally terminate when all
	# processors exit and Systems will do the same. However, Systems will almost always
	# have &Interface processors keeping the System in a functioning state.
	# Systems also have environment data that can be easily referenced by the running
	# processors.

	# [ Properties ]

	# /sys_identifier/
		# URL identifying the System's implementation.
		# Ideally, a valid URL providing documentation.
	# /sys_properties/
		# Storage dictionary for System properties.
		# Usually accessed using &sys_data for automatic initialization of data sets.
	"""

	@property
	def sys_closed(self) -> bool:
		"""
		# Whether the System has running Interface processors that explicitly
		# support external interactions.
		"""

		if Interface in self.processors:
			if len(self.processors[Interface]) > 0:
				return False

		return True

	def sys_if(self, Class:type) -> typing.Sequence[type]:
		"""
		# Return the set of Interface instances with the given &Class.
		"""

		return [
			x for x in self.processors[Interface]
			if isinstance(x, Class)
		]

class Transport(Context):
	"""
	# Essentially, the Connection class. Transport Contexts manage the I/O
	# designated for a given Transaction sector.

	# The Transaction Context that manages the stack of protocols
	# used to facilitate arbitrary I/O streams. For application protocols,
	# this class should be subclassed to implement protocol specific features
	# and manage transport stack connectivity.

	# [ Properties ]

	# /(&bool)transport_contraint/
		# Whether the transport is constrainted to `'input'` or `'output'`.
		# &None if the transport is bidirectional.
	# /(&tuple)transport_protocols/
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

class Subprocess(Processor):
	"""
	# A Processor that represents a *set* of Unix subprocesses.

	# Primarily exists to map process exit events to processor exits and
	# management of subprocessor metadata such as the Process-Id of the child.
	"""

	def __init__(self, *pids):
		self.process_exit_events = {}
		self.active_processes = set(pids)

	def structure(self):
		p = [
			x for x in [
				('active_processes', self.active_processes),
				('process_exit_events', self.process_exit_events),
			] if x[1]
		]
		return (p, ())

	@property
	def only(self):
		"""
		# The exit event of the only Process-Id. &None or the pair (pid, exitcode).
		"""

		for i in self.process_exit_events:
			return i, self.process_exit_events.get(i)

		return None

	def sp_exit(self, pid, event):
		# Target of the system event, this may be executed in cases
		# where the Processor has exited.

		# Being that this is representation of a resource that is not
		# actually controlled by the Processor, it will continue
		# to update the state. However, the exit event will only
		# occur if the Sector is consistent.

		self.process_exit_events[pid] = event
		self.active_processes.discard(pid)

		if not self.active_processes:
			self.active_processes = ()
			self._pexe_state = -1

			# Don't exit if interrupted; maintain position in hierarchy.
			if not self.interrupted:
				self.exit()

	def sp_signal(self, signo, send_signal=os.kill):
		"""
		# Send the given signal number (os.kill) to the active processes
		# being managed by the instance.
		"""

		for pid in self.active_processes:
			send_signal(pid, signo)
	signal = sp_signal # REMOVE

	def signal_process_group(self, signo, send_signal=os.kill):
		"""
		# Like &signal, but send the signal to the process group instead of the exact process.
		"""

		for pid in self.active_processes:
			send_signal(-pid, signo)

	def actuate(self):
		"""
		# Initialize the system event callbacks for receiving process exit events.
		"""

		proc = self.context.process
		track = proc.kernel.track
		callback = self.sp_exit

		for pid in self.active_processes:
			try:
				track(pid)
				proc.system_event_connect(('process', pid), self, callback)
			except OSError as err:
				if err.errno != errno.ESRCH:
					raise
				# Doesn't exist or already exited. Try to reap.
				self.ctx_enqueue_task(functools.partial(callback, pid, libexec.reap(pid)))

	def check(self):
		"""
		# Initialize the system event callbacks for receiving process exit events.
		"""

		proc = self.context.process
		reap = libexec.reap
		untrack = proc.kernel.untrack
		callback = self.sp_exit

		# Validate that the process exists; it may have exited before .track() above.
		# Apparently macos has a race condition here and a process that has exited
		# prior to &track will not get the event. This loop checks to make sure
		# that the process exists and whether or not it has exit status.
		finished = False
		proc_set = iter(list(self.active_processes))
		while not finished:
			try:
				for pid in proc_set:
					os.kill(pid, 0) # Looking for ESRCH errors.

					d = reap(pid)
					if not d.running:
						untrack(pid)
						proc.system_event_disconnect(('process', pid))
						self.sp_exit(pid, d)
						continue
				else:
					finished = True
			except OSError as err:
				if err.errno != errno.ESRCH:
					raise
				untrack(pid)
				proc.system_event_disconnect(('process', pid))
				self.sp_exit(pid, reap(pid))

	def terminate(self, by=None):
		"""
		# If the process set isn't terminating, issue SIGTERM
		# to all of the currently running processes.
		"""

		if not self.terminating:
			super().terminate(by=by)
			self.sp_signal(15)

	def interrupt(self, by=None, send_signal=os.kill):
		"""
		# Interrupt the running processes by issuing a SIGKILL signal.
		"""

		for pid in self.active_processes:
			try:
				send_signal(pid, 9)
			except ProcessLookupError:
				pass

	def abort(self, by=None):
		"""
		# Interrupt the running processes by issuing a SIGQUIT signal.
		"""

		r = super().interrupt(by)
		self.sp_signal(signal.SIGQUIT)
		return r

class Recurrence(Processor):
	"""
	# Timer maintenance for recurring tasks.

	# Usually used for short term recurrences such as animations and human status updates.
	# Recurrences work by deferring the execution of the configured target after
	# each occurrence. This overhead means that &Recurrence is not well suited for
	# high frequency executions, but useful in cases where it is important
	# to avoid overlapping calls.
	"""

	def __init__(self, target):
		self.recur_target = target
		self._recur_inhibit = False

	def actuate(self):
		"""
		# Enqueue the initial execution of the recurrence.
		"""

		self.ctx_enqueue_task(self._recur_occur)

	def recur_execute(self):
		if self._recur_inhibit:
			return None

		try:
			return self.recur_target()
		except BaseException as exc:
			self.fault(exc)

	def _recur_occur(self):
		"""
		# Invoke a recurrence and use its return to schedule its next iteration.
		"""

		next_delay = self.recur_execute()

		if next_delay is None:
			if not self.interrupted:
				self.exit()
		else:
			self.controller.scheduler.defer(next_delay, self._recur_occur)

	def terminate(self, by=None):
		self._recur_inhibit = True
		self.exit()

	def interrupt(self):
		self._recur_inhibit = True

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

class Scheduler(Processor):
	"""
	# Time delayed execution of arbitrary callables.

	# Manages the set of alarms and &Recurrence's used by a &Sector.
	# Normally, only one Scheduler exists per and each Scheduler
	# instance chains from an ancestor creating a tree of heap queues.

	# [ Engineering ]
	# The &update method needs to be corrected to avoid the &scheduled_reference
	# stopgap. Currently, the weakmethod is used to allow the storage of the
	# scheduled event in case a cancellation is needed. Cancellation works
	# using a set of events and &Scheduler needs each transition to be unique
	# in order to perform cancellation at all.

	# The entire management of scheduled &transition events needs to be
	# rewritten along with some tweaks to chronometry's scheduler.
	"""

	scheduled_reference = None
	x_ops = None

	def structure(self):
		sr = ()
		now = libtime.now()
		items = list(self.state.schedule.items())
		pit = self.state.meter.snapshot()
		pit = now.__class__(pit)

		p = [
			('now', now.select('iso')),
		]

		p.extend([
			((pit.measure(ts)), callbacks)
			for ts, callbacks in items
		])

		return (p, sr)

	def actuate(self):
		self.state = libtime.Scheduler()
		self.persistent = True

		controller = self.controller

		if isinstance(controller, Unit):
			# Controller is the Unit, so the execution context is used
			# to provide the scheduling primitives.
			self.x_ops = (
				self.context.defer,
				self.context.cancel
			)
		else:
			controller = controller.controller

			while controller is not None:
				if controller.scheduler is not None:
					sched = controller.scheduler
					break
				controller = controller.controller

			self.x_ops = (
				sched.defer,
				sched.cancel,
			)

	@staticmethod
	def execute_weak_method(weakmethod):
		return weakmethod()()

	def update(self):
		"""
		# Update the scheduled transition callback.
		"""

		nr = weakref.WeakMethod(self.transition)
		if self.scheduled_reference is not None:
			self.x_ops[1](self.scheduled_reference)

		sr = self.scheduled_reference = functools.partial(self.execute_weak_method, nr)
		self.x_ops[0](self.state.period(), sr)

	def schedule(self, pit:libtime.Timestamp, *tasks, now=libtime.now):
		"""
		# Schedule the &tasks to be executed at the specified Point In Time, &pit.
		"""

		measure = now().measure(pit)
		return self.defer(measure, *tasks)

	def defer(self, measure, *tasks):
		"""
		# Defer the execution of the given &tasks by the given &measure.
		"""

		p = self.state.period()

		self.state.put(*[
			(measure, x) for x in tasks
		])

		if p is None:
			self.update()
		else:
			np = self.state.period()
			if np < p:
				self.update()

	def cancel(self, task):
		"""
		# Cancel the execution of the given task scheduled by this instance.
		"""

		self.state.cancel(task)

	def recurrence(self, callback):
		"""
		# Allocate a &Recurrence and dispatch it in the same &Sector as the &Scheduler
		# instance. The target will be executed immediately allowing it to identify
		# the appropriate initial delay.
		"""

		r = Recurrence(callback)
		self.controller.dispatch(r)
		return r

	def transition(self):
		"""
		# Execute the next task given that the period has elapsed.
		# If the period has not elapsed, reschedule &transition in order to achieve
		# finer granularity.
		"""

		if not self.functioning:
			# Do nothing if not inside the functioning window.
			return

		period = self.state.period
		get = self.state.get

		tasks = get()
		for task_objects in tasks:
			try:
				# Resolve weak reference.
				measure, scheduled_task = task_objects

				if scheduled_task is not None:
					scheduled_task()
			except BaseException as scheduled_task_exception:
				raise
				self.fault(scheduled_task_exception)
				break # don't re-schedule transition
		else:
			p = period()

			try:
				if p is not None:
					# re-schedule the transition
					self.update()
				else:
					# falls back to class attribute; None
					del self.scheduled_reference
			except BaseException as scheduling_exception:
				raise
				self.fault(scheduling_exception)

	def process(self, event, Point=libtime.core.Point, Measure=libtime.core.Measure):
		"""
		# Schedule the set of tasks.
		"""

		schedule = self.state.put
		p = self.state.period()

		for timing, task in event:
			if isinstance(timing, Point):
				measure = libtime.now().measure(timing)
			elif isinstance(timing, Measure):
				measure = timing
			else:
				raise ValueError("scheduler requires a libtime.Unit")

			schedule((measure, task))

		if p is None:
			self.update()
		else:
			np = self.state.period()
			if np < p:
				self.update()

	def interrupt(self):
		# cancel the transition callback
		if self.scheduled_reference is not None:
			self.x_ops[1](self.scheduled_reference)

class Thread(Processor):
	"""
	# A &Processor that runs a callable in a dedicated thread.
	"""

	def __init__(self, callable):
		self.callable = callable

	def trap(self):
		final = None
		try:
			self.callable(self)
			self.termination_started()
			# Must be enqueued to exit.
			final = self.exit
		except BaseException as exc:
			final = functools.partial(self.fault, exc)

		self.ctx_enqueue_task(final)

	def actuate(self):
		"""
		# Execute the dedicated thread for the transformer.
		"""

		self.context.execute(self, self.trap)

	def process(self):
		"""
		# No-op as the thread exists to emit side-effects.
		"""
		pass

class Interface(Processor):
	"""
	# A &Processor that is identified as a source of work for a Sector.
	# Significant in that if all &Interface instances are terminated, the Sector
	# itself should eventually terminate as well.

	# Subclasses are encouraged to use the (namespace)`if_` prefix to define methods
	# that are intended for outside use.

	# Methods that are present on interface instances can be used arbitrarily by
	# dependencies without establishing connections.

	# [ Properties ]

	# /if_identifier/
		# An identifier for the interface allowing Systems to be queried for particular
		# interface types.
	"""

	if_identifier = None

	def placement(self):
		"""
		# Returns &Interface. Constant placement for subclasses so
		# that &Interface instances may be quickly identified in &Sector processor sets.
		"""
		return Interface

	def if_connect(self, *parameters) -> Processor:
		"""
		# Establish a formal connection to the System requesting a particular
		# API set that can be used in conjunction with preserved state.

		# The returned &Processor is constructed to be dispatched in a local sector
		# which provides access to the functionality of a remote Transaction.
		"""

		raise NotImplementedError("interface subclass does not provide connections")

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

		# /slot
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
		# /packet
			# The sequence of sequences containing Kernel Port references (file descriptors).
		# /transports
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

class Condition(object):
	"""
	# A *reference* to a logical expression or logical function.

	# Conditional references are constructed from a subject object, attribute path, and parameters.
	# Used to clearly describe the objects that participate in a logical conclusion of interest.

	# Used by &Flow instances to describe the condition in which an obstruction is removed.
	# Conditions provide introspecting utilities the capacity to identify the cause of
	# an obstruction.
	"""

	__slots__ = ('focus', 'path', 'parameter')

	def __init__(self, focus, path, parameter = None):
		"""
		# [Parameters]
		# /focus
			# The root object that is safe to reference
		# /path
			# The sequence of attributes to resolve relative to the &focus.
		# /parameter
			# Determines the condition is a method and should be given this
			# as its sole parameter. &None indicates that the condition is a property.
		"""
		self.focus = focus
		self.path = path
		self.parameter = parameter

	def __bool__(self):
		condition = self.attribute()

		if self.parameter is not None:
			return condition(self.parameter)
		else:
			# property
			return condition

	def __repr__(self):
		if self is Inexorable:
			return 'Inexorable'

		try:
			attval = self.attribute()
		except:
			attval = '<exception>'

		return "<Condition [%r].%s == %r>" %(
			self.focus, '.'.join(self.path), attval
		)

	def attribute(self, ag=operator.attrgetter):
		return ag('.'.join(self.path))(self.focus)

# Little like an enum, but emphasis on the concept rather than enumeration.
class FlowControl(object):
	"""
	# Signal objects used to communicate flow control operations
	# for subflow management. These objects are used by &Catenation and &Distribution
	# to index operations.
	"""
	__slots__ = ()

	def __int__(self):
		ops = self.__class__.operations
		l = len(ops)
		for op, i in zip(ops, range(l)):
			if op is self:
				return i - (l // 2)

	def __repr__(self):
		return self.__class__.__name__ + '.' + self.__str__()

	def __str__(self):
		for k, v in self.__class__.__dict__.items():
			if v is self:
				return k

FlowControl.initiate = FlowControl()
FlowControl.clear = FlowControl()
FlowControl.transfer = FlowControl()
FlowControl.obstruct = FlowControl()
FlowControl.terminate = FlowControl()
FlowControl.overflow = FlowControl()
FlowControl.operations = (
	FlowControl.terminate,
	FlowControl.obstruct,
	FlowControl.transfer,
	FlowControl.clear,
	FlowControl.initiate,
)

# A condition that will never be true.
Inexorable = Condition(builtins, ('False',))

class Flow(Processor):
	"""
	# A Processor consisting of an arbitrary set of operations that
	# can connect to other &Flow instances in order to make a series
	# of transformations.

	# Flows are the primary mechanism used to stream events; generally,
	# anything that's a stream should be managed by &Flow instances in favor
	# of other event callback mechanisms.

	# [ Properties ]

	# /f_type/
		# The flow type describing what the instance does.
		# This property can be &None at the class level, but should be initialized
		# when an instance is created.

		# /(id)`source`/
			# Flow that primarily emits events for downstream processing.
		# /(id)`terminal`/
			# Flow processes events, but emits nothing.
		# /(id)`switch`/
			# Flow that takes events and distributes their transformation
			# to a mapping of receiving flows. (Diffusion)
		# /(id)`join`/
			# Flow that receives events from a set of sources and combines
			# them into a single stream.
		# /(id)`transformer`/
			# Flow emits events strictly in response to processing. Transformers
			# may buffer events as needed.
		# /&None/
			# Unspecified type.

	# /f_obstructions/
		# /&None/
			# No obstructions present.
		# /&typing.Mapping/
			# The objects that are obstructing the &Flow from
			# performing processing associated with the exact
			# condition causing it.

	# /f_monitors/
		# The set of callbacks used to signal changes in the flow's
		# &f_obstructed state.

		# /&None/
			# No monitors watching the flow state.

	# /f_downstream/
		# The &Flow instance that receives events emitted by the instance
		# holding the attribute.
	"""

	f_type = None
	f_obstructions = None
	f_monitors = None
	f_downstream = None
	f_upstream = None

	def f_connect(self, flow:Processor, partial=functools.partial, Ref=weakref.ref):
		"""
		# Connect the Flow to the given object supporting the &Flow interface.
		# Normally used with other Flows, but other objects may be connected.

		# Downstream is *not* notified of upstream obstructions. Events run
		# downstream and obstructions run up.
		"""
		if self.f_downstream:
			self.f_disconnect()

		# Downstreams do not need to be notified of upstream obstructions.
		# Even with output rate constraints, there is no need to apply
		# constraints if the write buffer is usually empty.

		# Events run downstream, obstructions run upstream.

		self.f_downstream = flow
		flow.f_upstream = Ref(self)
		flow.f_watch(self.f_obstruct, self.f_clear)
		self.f_emit = flow.process
	connect = f_connect

	def f_disconnect(self):
		"""
		# Disconnect from the downstream and cease emitting events into &f_downstream.
		"""

		flow = self.f_downstream
		if flow is not None:
			self.f_downstream = None
			flow.f_ignore(self.f_obstruct, self.f_clear)
			flow.f_upstream = None
		self.f_emit = self.f_discarding

	def f_collapse(self):
		"""
		# Connect the upstream to the downstream leaving the Flow &self
		# in a disconnected state with the old references remaining in place.
		"""
		upstream_ref = self.f_upstream
		upstream = upstream_ref()
		upstream.f_disconnect()
		downstream = self.f_downstream
		self.f_disconnect()

		upstream.f_connect(downstream)

		self.f_upstream = upstream_ref
		self.f_downstream = downstream

	def f_substitute(self, series):
		for us, ds in zip(series[0::1], series[1::1]):
			us.f_connect(ds)

		series[-1].f_connect(self.f_downstream)
		self.f_upstream().f_connect(series[0])

	def __repr__(self):
		return '<' + self.__class__.__name__ + '[' + hex(id(self)) + ']>'

	def structure(self):
		"""
		# Reveal the obstructions and monitors of the Flow.
		"""

		sr = ()
		p = [
			x for x in [
				('f_obstructions', self.f_obstructions),
				('f_monitors', self.f_monitors),
			] if x[1] is not None
		]

		return (p, sr)

	def actuate(self):
		"""
		# Actuate the Flow for use within the controlling Sector.
		"""
		super().actuate()

	def terminate(self, by=None):
		"""
		# Drain the Flow and finish termination by signalling the controller
		# of its exit.
		"""

		if self.terminated or self.terminating or self.interrupted:
			return False

		self.terminator = by
		self.termination_started()

		self.ctx_enqueue_task(self._f_terminated)
		return True

	def f_terminate(self, context=None):
		"""
		# Termination signal received when the upstream no longer has
		# flow transfers for the downstream Flow.
		"""
		self._f_terminated()

	def _f_terminated(self):
		"""
		# Used by subclasses to issue downstream termination and exit.

		# Subclasses must call this or perform equivalent actions when termination
		# of the conceptual flow is complete.
		"""

		self.process = self.f_discarding
		self.f_emit = self.f_discarding

		self.termination_completed()

		if self.f_downstream:
			self.f_downstream.f_ignore(self.f_obstruct, self.f_clear)
			self.f_downstream.f_terminate(context=self)

		if self.controller:
			self.exit()

	def interrupt(self):
		self.process = self.f_discarding
		self.f_emit = self.f_discarding

		if self.f_downstream:
			# interrupt the downstream and
			# notify exit iff the downstream's
			# controller is functioning.
			ds = self.f_downstream
			ds.f_terminate(self)
			dsc = ds.controller
			if dsc is not None and dsc.functioning:
				dsc.exited(ds)

		return True

	def process(self, event, source=None):
		"""
		# Emit the &event directly to the downstream.
		"""

		self.f_emit(event, source=self)

	def f_emit(self, event, source=None):
		"""
		# Method replaced at runtime for selecting the recipient
		# of a processed event.
		"""

		pass

	@property
	def f_empty(self):
		"""
		# Whether the flow is actively performing a transfer.

		# This property returns &True in cases where the Flow's
		# state is such that it may independently send events downstream.

		# Flows that have buffers *should* implement this method.
		"""

		return True

	@property
	def f_obstructed(self):
		"""
		# Whether or not the &Flow is obstructed.
		"""

		return self.f_obstructions is not None

	@property
	def f_permanent(self, sum=sum) -> int:
		"""
		# Whether or not there are Inexorable obstructions present.
		# An integer specifying the number of &Inexorable obstructions or &None
		# if there are no obstructions.
		"""

		if self.f_obstructions:
			return sum([1 if x[1] is Inexorable else 0 for x in self.f_obstructions.values()])

	def f_obstruct(self, by, signal=None, condition=None):
		"""
		# Instruct the Flow to signal the cessation of transfers.
		# The cessation may be permanent depending on the condition.
		"""

		if not self.f_obstructions:
			first = True
			if self.f_obstructions is None:
				self.f_obstructions = {}
		else:
			first = False

		self.f_obstructions[by] = (signal, condition)

		# don't signal after termination/interruption.
		if first and self.f_monitors:
			# only signal the monitors if it wasn't already obstructed.
			for sentry in self.f_monitors:
				sentry[0](self)

	def f_clear(self, obstruction):
		"""
		# Clear the obstruction by the key given to &obstruction.
		"""

		cleared = False
		f_obs = self.f_obstructions
		if f_obs:
			if obstruction in f_obs:
				del f_obs[obstruction]

				if not f_obs:
					self.f_obstructions = None
					cleared = True

					# no more obstructions, notify the monitors
					if self.f_monitors:
						for sentry in self.f_monitors:
							sentry[1](self)

		return cleared

	def f_watch(self, obstructed, cleared):
		"""
		# Assign the given functions as callbacks to obstruction events.
		# First called when an obstruction occurs and second when its cleared.
		"""

		if self.f_monitors is None:
			self.f_monitors = set()
		self.f_monitors.add((obstructed, cleared))

		if self.f_obstructed:
			obstructed(self)

	def f_ignore(self, obstructed, cleared):
		"""
		# Stop watching the Flow's obstructed state.
		"""

		if self.f_monitors:
			self.f_monitors.discard((obstructed, cleared))

	def f_discarding(self, event, source = None):
		"""
		# Assigned to &process and &f_emit after termination and interrupt in order
		# to keep overruns from exercising the Transformations.
		"""

		pass

class Mitre(Flow):
	"""
	# The joining flow between input and output.

	# Subclasses of this flow manage the routing of protocol requests.
	"""
	f_type = 'mitre'

	def f_connect(self, flow:Processor):
		"""
		# Connect the given flow as downstream without inheriting obstructions.
		"""

		# Similar to &Flow, but obstruction notifications are not carried upstream.
		self.f_downstream = flow
		self.f_emit = flow.process

class Sockets(Mitre):
	"""
	# Mitre for transport flows created by &System in order to accept sockets.
	"""

	def __init__(self, reference, router):
		self.m_reference = reference
		self.m_router = router

	def process(self, event, source=None):
		"""
		# Accept the event, but do nothing as Terminals do not propogate events.
		"""
		update = self.m_router((self.m_reference, event))
		if update:
			self.m_router = update

	def atexit(self, receiver):
		if receiver != self.f_downstream.f_terminate:
			# Sockets() always sends to null, don't bother with a atexit entry.
			return super().atexit(receiver)

class Transformation(Flow):
	"""
	# A flow that performs a transformation on the received events.
	"""

	def __init__(self, transform):
		self.tf_transform = transform

	def process(self, event, source=None):
		self.f_emit(self.tf_transform(event))

	terminate = Flow._f_terminated

class Iteration(Flow):
	"""
	# Flow that emits the contents of an &collections.abc.Iterator until
	# an obstruction occurs or the iterator ends.
	"""
	f_type = 'source'

	def f_clear(self, *args) -> bool:
		"""
		# Override of &Flow.f_clear that enqueues an &it_transition call
		# if it's no longer obstructed.
		"""

		if super().f_clear(*args):
			self.ctx_enqueue_task(self.it_transition)
			return True
		return False

	def it_transition(self):
		"""
		# Emit the next item in the iterator until an obstruction occurs or
		# the iterator is exhausted.
		"""

		for x in self.it_iterator:
			# Emit has to be called directly to discover
			# any obstructions created downstream.
			self.f_emit(x, source=self)
			if self.f_obstructed:
				# &f_clear will re-queue &it_transition after
				# the obstruction is cleared.
				break
		else:
			self.terminate(by='end of iterator')

	def __init__(self, iterator):
		"""
		# [ Parameters ]

		# /iterator
			# The iterator that produces events.
		"""

		self.it_iterator = iter(iterator)

	def actuate(self):
		super().actuate()
		if not self.f_obstructed:
			self.ctx_enqueue_task(self.it_transition)

	def process(self, it, source=None):
		"""
		# Raises exception as &Iteration is a source.
		"""
		raise Exception('Iteration only produces')

class Collection(Flow):
	"""
	# Terminal &Flow collecting the events into a buffer for processing after
	# termination.
	"""
	f_type = 'terminal'

	def __init__(self, storage, operation):
		super().__init__()
		self.c_storage = storage
		self.c_operation = operation

	@classmethod
	def list(Class):
		"""
		# Construct a &Collection instance that appends all events into a &list
		# instance.
		"""
		l = []
		return Class(l, l.append)

	@classmethod
	def dict(Class, initial=None):
		"""
		# Construct a &Collection instance that builds the contents of a
		# mapping from sequences of key-value pairs.
		"""
		if initial is None:
			initial = {}
		def collect_mapping_add(x, collect_mapping_set=initial.__setitem__):
			collect_mapping_set(*x)

		return Class(initial, collect_mapping_add)

	@classmethod
	def set(Class):
		s = set()
		return Class(s, s.add)

	@staticmethod
	def _buffer_operation(event, barray=None, op=bytearray.__iadd__, reduce=functools.reduce):
		reduce(op, event, barray)

	@classmethod
	def buffer(Class, initial=None, partial=functools.partial, bytearray=bytearray):
		"""
		# Construct a &Collection instance that accumulates data from sequences
		# of data into a single &bytearray.
		"""
		if initial is None:
			initial = bytearray()
		return Class(initial, partial(Class._buffer_operation, barray=initial))

	def process(self, obj, source=None):
		self.c_operation(obj)

class Parallel(Flow):
	"""
	# A dedicated thread for processing events emitted to the Flow.

	# Term Parallel being used as the actual function is ran in parallel to
	# the &Flow in which it is participating in.

	# The requisite function should have the following signature:

	# #!/pl/python
		def thread_function(transformer, queue, *optional):
			...

	# The queue provides access to the events that were received by the Transformer,
	# and the &transformer argument allows the thread to cause obstructions by
	# accessing its controller.
	"""

	def __init__(self, target:typing.Callable, *parameters):
		self.pf_target = target
		self.pf_parameters = parameters
		self.pf_queue = queue.Queue()
		self._pf_put = self.pf_queue.put

	def terminate(self, by=None):
		"""
		# Initiate termination of the thread.
		"""
		if self.terminated or self.terminating or self.interrupted:
			return False

		self.termination_started()
		self._pf_put(None)
		return True

	def trap(self):
		"""
		# Internal; Trap exceptions in order to map them to faults.
		"""
		try:
			self.pf_target(self, self.pf_queue, *self.pf_parameters)
			self.ctx_enqueue_task(self._f_terminated)
		except BaseException as exc:
			self.context.enqueue(functools.partial(self.fault, exc))
			pass # The exception is managed by .fault()

	def process(self, event):
		"""
		# Send the event to the queue that the Thread is connected to.
		# Injections performed by the thread will be enqueued into the main task queue.
		"""

		self._pf_put(event)

	def actuate(self):
		"""
		# Execute the dedicated thread for the transformer.
		"""

		super().actuate()
		self.process = self._pf_put
		self.context.execute(self, self.trap)

class Transports(Flow):
	"""
	# Transports represents a stack of protocol layers and manages their
	# initialization and termination so that the outermost layer is
	# terminated before the inner layers, and vice versa for initialization.

	# Transports are primarily used to manage protocol layers like TLS where
	# the flows are completely dependent on the &Transports.

	# [ Properties ]

	# /tf_termination_index/
		# Not Implemented.

		# /(&int)`x > 0`/
			# The lowest index of the stack that has terminated
			# in both directions. When &tf_termination_index is equal
			# to `1`, the transports will reach a terminated
			# state and the connected flows will receive terminate events.
		# /&None/
			# No part of the stack has terminated.

	# /tf_polarity/
		# /`-1`/
			# The transport is sending events out.
		# /`+1`/
			# The transport is receiving events in.

	# /tf_operations/
		# The operations used to apply the layers for the respective direction.

	# /operation_set/
		# Class-wide dictionary containing the functions
		# needed to resolve the transport operations used by a layer.

	# [ Engineering ]
	# Needs to be renamed in order to avoid confusion with Transport(Context).
	"""

	operation_set = {}

	@classmethod
	def create(Class, transports, Stack=list):
		"""
		# Create a pair of &Protocols instances.
		"""

		i = Class(1)
		o = Class(-1)

		i._tf_opposite = weakref.ref(o)
		o._tf_opposite = weakref.ref(i)

		stack = i.tf_stack = o.tf_stack = Stack(transports)

		ops = [
			Class.operation_set[x.__class__](x) for x in stack
		]
		i.tf_operations = [x[0] for x in ops]

		# Output must reverse the operations in order to properly
		# layer the transports.
		o.tf_operations = [x[1] for x in ops]
		o.tf_operations.reverse()

		return (i, o)

	polarity = 0 # neither input nor output.
	def __init__(self, polarity:int):
		self._tf_opposite = None
		self.tf_stack = None
		self.tf_polarity = polarity
		self.tf_termination_index = None

	def __repr__(self, format="<{path} [{stack}]>"):
		path = self.__class__.__module__.rsplit('.', 1)[-1]
		path += '.' + self.__class__.__qualname__
		return format.format(path=path, stack=repr(self.tf_stack))

	def structure(self):
		return ((
			('polarity', self.tf_polarity),
			('stack', self.tf_stack),
		), ())

	@property
	def opposite(self):
		"""
		# The transformer of the opposite direction for the Transports pair.
		"""
		return self._tf_opposite()

	def tf_empty(self):
		self.process(())

	def terminal(self):
		self.process(())

		if not self.tf_stack:
			self._f_terminated()
			return

		if not self.tf_stack[-1].terminated:
			o = self.opposite
			if o.terminating and o.functioning:
				# Terminate other side if terminating and functioning.
				self.tf_stack[-1].terminate(-self.tf_polarity)
				o.process(())

	def process(self, events, source=None):
		"""
		# Process the given events with the referenced I/O operations.

		# [ Engineering ]
		# Currently raises exception when deadlocked, should dispatch
		# a Fatal with details.
		"""
		if not self.tf_operations:
			# Opposite cannot have work if empty.
			self.f_emit(events) # Empty transport stack acts a passthrough.
			return

		opposite_has_work = False

		for ops in self.tf_operations:
			# ops tuple callables:
			# 0: transfer data into and out of the transport
			# 1: Current direction has transfers
			# 2: Opposite direction has transfers
			# (Empty transfers can progress data)

			# put all events into the transport layer's buffer.
			events = ops[0](events)

			if opposite_has_work is False and ops[2]():
				opposite_has_work = True
		else:
			# No processing if empty.
			self.f_emit(events)

		# Termination must be checked everytime unless process() was called from here
		if opposite_has_work:
			# Use recursion on purpose and allow
			# the maximum stack depth to block an infinite loop.
			# from a poorly implemented protocol.
			self._tf_opposite().process(())
			x = 0
			for ops in self.tf_operations:
				if ops[2]():
					x += 1
					break
			if x and self.polarity == -1 and self._tf_opposite().terminating:
				# The Input side of the Pair has terminated and
				# there is still opposite work pending.
				raise Exception("transport stack deadlock")

		stack = self.tf_stack
		opp = self._tf_opposite()
		while stack and stack[-1].terminated:
			# Full Termination. Pop item after allowing the opposite to complete.
			# This needs to be done as the transport needs the ability
			# to flush any remaining events in the opposite direction.

			protocol = stack[-1]
			del stack[-1] # both sides; stack is shared.

			# operations is perspective sensitive
			if self.tf_polarity == 1:
				# recv/input
				del self.tf_operations[-1]
				del opp.tf_operations[0]
				self.f_downstream.f_terminate()
				self.f_disconnect()
			else:
				# send/output
				del self.tf_operations[0]
				del opp.tf_operations[-1]
				opp.f_downstream.f_terminate()
				opp.f_disconnect()
		else:
			if not stack:
				# empty stack. check for terminating conditions.
				if self.terminating:
					self._f_terminated()
				if opp is not None and opp.terminating:
					opp._f_terminated()

	def f_terminate(self, context=None):
		"""
		# Manage upstream flow termination by signalling
		# the internal transport layers.
		"""

		stack = self.tf_stack
		if not stack:
			# Termination is complete when the stack's layers
			# have been completed or interrupted.
			self._f_terminated()
			return
		elif self.tf_polarity == 1:
			# Receive termination effectively interrupts receive transfers.
			# When a terminating receive is expected to perform transfers,
			# we can safely interrupt if it's not satisfied by an empty transfer.
			self.termination_started()
			for x in stack:
				x.terminate(1)
			self.tf_empty()
			if stack:
				self.f_downstream.f_terminate()
		else:
			assert self.tf_polarity == -1

			# Output Flow. Termination is passed to the top of the stack.
			self.tf_stack[-1].terminate(self.tf_polarity)
			self.tf_empty()

	def terminate(self, by=None):
		"""
		# Reject the request to terminate as Transports
		# state is dependent on Flow state.
		"""
		pass

class Kernel(Flow):
	"""
	# Flow moving data in or out of the operating system's kernel.
	# The &KInput and &KOutput implementations providing for the necessary specializations.
	"""
	k_status = None

	def inject(self, events):
		return self.f_emit(events)

	def f_clear(self, *args):
		r = super().f_clear(*args)
		if self.f_obstructed:
			pass
		return r

	def __init__(self, transit=None):
		self.transit = transit
		self.acquire = transit.acquire
		transit.link = self
		super().__init__()

	def actuate(self):
		self.context._sys_traffic_attach(self.transit)

	def k_meta(self):
		if self.transit:
			return self.transit.port, self.transit.endpoint()
		else:
			return self.k_status

	def __repr__(self):
		c = self.__class__
		mn = c.__module__.rsplit('.', 1)[-1]
		qn = c.__qualname__
		port, ep = self.k_meta()

		if self.transit is None:
			res = "(no transit)"
		else:
			if self.transit.resource is None:
				res = "none"
			else:
				res = str(len(self.transit.resource))

		s = '<%s.%s(%s) RL:%s [%s] at %s>' %(
			mn, qn,
			str(ep),
			res,
			str(port),
			hex(id(self))
		)

		return s

	def structure(self):
		p = []
		kp, ep = self.k_meta()
		p.append(('kport', kp.fileno))
		p.append(('endpoint', str(ep)))
		if self.transit is not None:
			r = self.transit.resource
			p.append(('resource', len(r) if r is not None else 'none'))

		return (p, ())

	def k_transition(self):
		# Called when the resource was exhausted
		# Unused atm and pending deletion.
		raise NotImplementedError("Kernel flows must implement transition")

	def k_kill(self):
		"""
		# Called by the controlling &Flow, acquire status information and
		# unlink the transit.
		"""

		t = self.transit
		self.transit = None
		self.k_status = (t.port, t.endpoint())
		t.link = None # signals I/O loop to not inject.
		t.terminate() # terminates one direction.

		return t

	def interrupt(self):
		if self.transit is not None:
			self.k_kill()

	def f_terminated(self):
		# THIS METHOD IS NOT CALLED IF TERMINATE/INTERRUPT() WAS USED.
		#assert not self.interrupted and not self.terminated

		# Called when the termination condition is received,
		# but *after* any transfers have been injected.

		# &.traffic calls this when it sees termination of the transit.

		if self.transit is None:
			# terminate has already been ran; status is *likely* present
			pass
		else:
			self.k_kill()

			# No need to run transit.terminate() as this is only
			# executed by io.traffic in response to shutdown.

			# Exception is not thrown as the transport's error condition
			# might be irrelevant to the success of the application.
			# If a transaction was successfully committed and followed
			# with a transport error, it's probably appropriate to
			# show the transport issue, if any, as a warning.
			if not self.terminated:
				self.exit()
			if 0:
				self.f_obstruct('kernel port closed', None, Inexorable)

	def process(self, event, source=None):
		raise NotImplementedError("kernel flows must implement process")

	def inject(self, events):
		self.f_emit(events)

	@property
	def k_transferring(self, len=len):
		"""
		# The length of the buffer being transferred into or out of the kernel.

		# &None if no transfer is currently taking place.
		"""
		x = self.transit
		if x is not None:
			x = x.resource
			if x is not None:
				return len(x)

		return None

class KInput(Kernel):
	"""
	# Flow that continually allocates memory for a transit transferring data into the process.
	"""

	allocate_integer_array = (array.array("i", [-1]).__mul__, 24)
	allocate_byte_array = (bytearray, 1024*4)

	@classmethod
	def sockets(Class, transit):
		"""
		# Allocate a &KInput instance for transferring accepted sockets.
		"""
		return Class(transit, allocate=Class.allocate_integer_array)

	def __init__(self, transit, allocate=allocate_byte_array):
		super().__init__(transit=transit)

		self.ki_allocate = allocate[0]
		self.ki_resource_size = allocate[1]

	def f_terminated(self):
		if self.transit is None:
			# terminate has already been ran; status is *likely* present
			return

		self.k_kill()

		# Exception is not thrown as the transport's error condition
		# might be irrelevant to the success of the application.
		# If a transaction was successfully committed and followed
		# with a transport error, it's probably appropriate to
		# show the transport issue, if any, as a warning.
		self._f_terminated()

	def k_transition(self):
		"""
		# Transition in the next buffer provided that the Flow was not obstructed.
		"""

		if self.f_obstructed:
			# Don't allocate another buffer if the flow has been
			# explicitly obstructed by the downstream.
			return

		alloc = self.ki_allocate(self.ki_resource_size)
		self.acquire(alloc)

	def process(self, event, source=None):
		"""
		# Normally ignored, but will induce a transition if no transfer is occurring.
		"""

		if self.transit.resource is None:
			self.k_transition()

class KOutput(Kernel):
	"""
	# Flow that transfers emitted events to be transferred into the kernel.

	# The queue is limited to a certain number of items rather than a metadata constraint;
	# for instance, the sum of the length of the buffer entries. This allows the connected
	# Flows to dynamically choose the buffer size by adjusting the size of the events.
	"""

	ko_limit = 16

	@property
	def ko_overflow(self):
		"""
		# Queue entries exceeds limit.
		"""
		return len(self.ko_queue) > self.ko_limit

	@property
	def f_empty(self):
		return (
			self.transit is not None and \
			len(self.ko_queue) == 0 and \
			self.transit.resource is None
		)

	def __init__(self, transit, Queue=collections.deque):
		super().__init__(transit=transit)
		self.ko_queue = Queue()
		self.k_transferred = None

	def k_transition(self):
		# Acquire the next buffer to be sent.
		if self.ko_queue:
			nb = self.ko_queue.popleft()
			self.acquire(nb)
			self.k_transferred = 0
		else:
			# Clear obstruction when and ONLY when the buffer is emptied.
			# This is done to avoid thrashing.
			self.k_transferred = None
			self.f_clear(self)

			if self.terminating:
				self.transit.terminate()

	def process(self, event, source=None, len=len):
		"""
		# Enqueue a sequence of transfers to be processed by the Transit.
		"""

		# Events *must* be processed, so extend the queue unconditionally.
		self.ko_queue.extend(event)

		if self.k_transferred is None:
			# nothing transferring, so there should be no transfer resources (Transit/Detour)
			self.k_transition()
		else:
			# Set obstruction if the queue size exceeds the limit.
			if len(self.ko_queue) > self.ko_limit:
				self.f_obstruct(self, None,
					Condition(self, ('ko_overflow',))
				)

	def f_terminate(self, context=None):
		if self.terminating:
			return False

		# Flow-level Termination occurs when the queue is clear.
		self.termination_started()
		self.terminator = context

		if self.f_empty:
			# Only terminate transit if it's empty.
			self.transit.terminate()
			self.exit()

		# Note termination signalled.
		return True

	def terminate(self, by=None):
		self.f_terminate(by)

ProtocolTransactionEndpoint = typing.Callable[[
	Processor, Layer, Layer, typing.Callable[[Flow], None]
], None]

class Null(Flow):
	"""
	# Flow that has no controller, ignores termination, and emits no events.

	# Conceptual equivalent of (system:filepath)`/dev/null`.
	"""
	controller = None
	f_type = 'terminal'

	def __init__(self):
		pass

	@property
	def f_emit(self):
		"""
		Immutable property inhibiting invalid connections.
		"""
		return self.f_discarding

	@f_emit.setter
	def f_emit(self, value):
		"""
		# Desregard update likely setting f_discarding.
		"""
		pass

	def subresource(*args):
		raise Exception("libio.Null cannot be acquired")
	def atexit(*args):
		raise Exception("libio.Null never exits")
	def f_null_obstructions(*args):
		raise Exception("libio.Null is never obstructed")
	f_clear = f_null_obstructions
	f_obstruct = f_null_obstructions

	def f_connect(self, downstream:Flow):
		"""
		# Induces termination in downstream.
		"""
		downstream.terminate(by=self)

	def f_watch(*args):
		pass
	def f_ignore(*args):
		pass

	def terminate(self, by=None):
		pass
	def interrupt(self):
		pass
	def process(self, event, source=None):
		pass
null = Null()

class Funnel(Flow):
	"""
	# A union of events that emits data received from a set of &Flow instances.

	# The significant distinction being that termination from &Flow instances are ignored.
	"""

	def f_terminate(self, context=None):
		pass

class Traces(Flow):
	def __init__(self):
		super().__init__()
		self.monitors = dict()

	def monitor(self, identity, callback):
		"""
		# Assign a monitor to the Meta Reflection.

		# [ Parameters ]

		# /identity
			# Arbitrary hashable used to refer to the callback.

		# /callback
			# Unary callable that receives all events processed by Trace.
		"""

		self.monitors[identity] = callback

	def trace_process(self, event, source=None):
		for x in self.monitors.values():
			x(event)

		self.f_emit(event)
	process = trace_process

	@staticmethod
	def log(event, title=None, flush=sys.stderr.flush, log=sys.stderr.write):
		"""
		# Trace monitor for printing events.
		"""
		if self.title:
			trace = ('EVENT TRACE[' + title + ']:' + repr(event)+'\n')
		else:
			trace = ('EVENT TRACE: ' + repr(event)+'\n')

		if self.condition is not None and self.condition:
			self.log(trace)
			self.flush()
		else:
			self.log(trace)
			self.flush()

		self.f_emit(event)

class Catenation(Flow):
	"""
	# Sequence a set of flows in the enqueued order.

	# Emulates parallel operation by facilitating the sequenced delivery of
	# a sequence of flows where the first flow is carried until completion before
	# the following flow may be processed.

	# Essentially, this is a buffer array that uses Flow termination signals
	# to manage the current working flow and queues to buffer the events to be emitted.

	# [ Untested ]

		# - Recursive transition() calls.

	# [ Properties ]

	# /cat_order/
		# Queue of &Layer instances dictating the order of the flows.
	# /cat_connections/
		# Mapping of connected &Flow instances to their corresponding
		# queue, &Layer, and termination state.
	# /cat_flows/
		# Connection identifier mapping to a connected &Flow.
	"""
	f_type = 'join'

	def __init__(self, Queue=collections.deque):
		self.cat_order = Queue() # order of flows deciding next in line

		# TODO: Likely need a weakkeydict here for avoiding cycles.
		self.cat_connections = dict() # Flow -> (Queue, Layer, Termination)
		self.cat_flows = dict() # Layer -> Flow
		self.cat_events = [] # event aggregator

	def cat_overflowing(self, flow):
		"""
		# Whether the given flow's queue has too many items.
		"""

		q = self.cat_connections[flow][0]

		if q is None:
			# front flow does not have a queue
			return False
		elif len(q) > 8:
			return True
		else:
			return False

	def cat_transfer(self, events, source, fc_xfer = FlowControl.transfer):
		"""
		# Emit point for Sequenced Flows
		"""

		# Look up layer for protocol join downstream.
		q, layer, term = self.cat_connections[source]

		if layer == self.cat_order[0]:
			# Only send if &:HoL.
			if not self.cat_events:
				self.ctx_enqueue_task(self.cat_flush)
			self.cat_events.append((fc_xfer, layer, events))
		else:
			if q is not None:
				q.append(events)
				if not source.f_obstructed and self.cat_overflowing(source):
					source.f_obstruct(self, None, Condition(self, ('cat_overflowing',), source))
			else:
				raise Exception("flow has not been connected")

	def process(self, events, source):
		if source in self.cat_connections:
			return self.cat_transfer(events, source)
		else:
			self.cat_order.extend(events)
			return [
				(x, functools.partial(self.cat_connect, x)) for x in events
			]

	def cat_terminate(self, subflow):
		cxn = self.cat_connections[subflow]
		q, layer, term = cxn

		if layer == self.cat_order[0]:
			# Head of line.
			self.cat_transition()
		else:
			# Not head of line. Update entry's termination state.
			self.cat_connections[by] = (q, layer, True)

	def f_terminate(self, context=None):
		cxn = self.cat_connections.get(context)

		if cxn is None:
			# Not termination from an upstream subflow.
			# Note as terminating.
			if not self.terminating:
				self.termination_started()
				self.cat_flush()
		else:
			self.cat_terminate(context)

	def terminate(self, by=None):
		"""
		# Termination signal ignored. Flow state dictates terminal state.
		"""
		return False

	def cat_flush(self, len=len):
		"""
		# Flush the accumulated events downstream.
		"""
		events = self.cat_events
		self.cat_events = [] # Reset before emit in case of re-enqueue.
		self.f_emit(events, self)

		if self.terminating is True and len(self.cat_order) == 0:
			# No reservations in a terminating state finishes termination.
			self._f_terminated()

	def cat_reserve(self, layer):
		"""
		# Reserve a position in the sequencing of the flows. The given &layer is the reference
		# object used by &cat_connect in order to actually connect flows.
		"""

		self.cat_order.append(layer)

	def cat_connect(self, layer, flow, fc_init=FlowControl.initiate, Queue=collections.deque):
		"""
		# Connect the flow to the given layer signalling that its ready to process events.
		"""

		assert bool(self.cat_order) is True # Presume layer enqueued.

		if self.cat_order[0] == layer:
			# HoL connect, emit open.
			if flow is not None:
				self.cat_connections[flow] = (None, layer, None)

			self.cat_flows[layer] = flow

			if not self.cat_events:
				self.ctx_enqueue_task(self.cat_flush)
			self.cat_events.append((fc_init, layer))
			if flow is None:
				self.cat_transition()
			else:
				flow.f_connect(self)
		else:
			# Not head of line, enqueue events iff flow is not None.
			self.cat_flows[layer] = flow
			if flow is not None:
				self.cat_connections[flow] = (Queue(), layer, None)
				flow.f_connect(self)

	def cat_drain(self, fc_init=FlowControl.initiate, fc_xfer=FlowControl.transfer):
		"""
		# Drain the new head of line emitting any queued events and
		# updating its entry in &cat_connections to immediately send events.
		"""

		assert bool(self.cat_order) is True # Presume  layer enqueued.

		# New head of line.
		f = self.cat_flows[self.cat_order[0]]
		q, l, term = self.cat_connections[f]

		# Terminate signal or None is fine.
		if not self.cat_events:
			self.ctx_enqueue_task(self.cat_flush)

		add = self.cat_events.append
		add((fc_init, l))
		pop = q.popleft
		while q:
			add((fc_xfer, l, pop()))

		if term is None:
			self.cat_connections[f] = (None, l, term)
			f.f_clear(self)
		else:
			# Termination was caught and stored.
			# The enqueued data was the total transfer.
			self.cat_transition()

	def cat_transition(self, fc_terminate=FlowControl.terminate, exiting_flow=None, getattr=getattr):
		"""
		# Move the first enqueued flow to the front of the line;
		# flush out the buffer and remove ourselves as an obstruction.
		"""

		assert bool(self.cat_order) is True

		# Kill old head of line.
		l = self.cat_order.popleft()
		f = self.cat_flows.pop(l)
		if f is not None:
			# If Flow is None, cat_connect(X, None)
			# was used to signal layer only send.
			del self.cat_connections[f]

		if not self.cat_events:
			self.ctx_enqueue_task(self.cat_flush)
		self.cat_events.append((fc_terminate, l))

		# Drain new head of line queue.
		if self.cat_order:
			if self.cat_order[0] in self.cat_flows:
				# Connected, drain and clear any obstructions.
				self.ctx_enqueue_task(self.cat_drain)

class Division(Flow):
	"""
	# Coordination of the routing of a protocol's layer content.

	# Protocols consisting of a series of requests, HTTP for instance,
	# need to control where the content of a request goes. &QueueProtocolInput
	# manages the connections to actual &Flow instances that delivers
	# the transformed application level events.
	"""
	f_type = 'fork'

	def __init__(self):
		super().__init__()
		self.div_queues = collections.defaultdict(collections.deque)
		self.div_flows = dict() # connections
		self.div_initiations = []

	def process(self, events, source=None):
		"""
		# Direct the given events to their corresponding action in order to
		# map protocol stream events to &Flow instances.
		"""

		ops = self.div_operations
		for event in events:
			ops[event[0]](self, *event)

		if self.div_initiations:
			# Aggregate initiations for single propagation.
			self.f_emit(self.div_initiations)
			self.div_initiations = []

	def interrupt(self, by=None, fc_terminate=FlowControl.terminate):
		"""
		# Interruptions on distributions translates to termination.
		"""

		# Any connected div_flows are subjected to interruption here.
		# Closure here means that the protocol state did not manage
		# &close the transaction and we need to assume that its incomplete.
		for layer, flow in self.div_flows.items():
			if flow in {fc_terminate, None}:
				continue
			flow.f_terminate(context=self)

		return True

	def f_terminate(self, context=None):
		self.interrupt()
		self._f_terminated()

	def div_initiate(self, fc, layer, partial=functools.partial):
		"""
		# Initiate a subflow using the given &layer as its identity.
		# The &layer along with a callable performing &div_connect will be emitted
		# to the &Flow.f_connect downstream.
		"""

		self.div_flows[layer] = None
		connect = partial(self.div_connect, layer)

		# Note initiation and associate connect callback.
		self.div_initiations.append((layer, connect))

	def div_connect(self, layer:Layer, flow:Flow, fc_terminate=FlowControl.terminate):
		"""
		# Associate the &flow with the &layer allowing transfers into the flow.

		# Drains the queue that was collecting events associated with the &layer,
		# and feeds them into the flow before destroying the queue. Layer connections
		# without queues are the head of the line, and actively receiving transfers
		# and control events.
		"""

		if flow is None:
			# None connect means that there is no content to be transferred.
			del self.div_flows[layer]
			return

		flow.f_watch(self.f_obstruct, self.f_clear)
		cflow = self.div_flows.pop(layer, None)

		self.div_flows[layer] = flow

		# drain the queue
		q = self.div_queues[layer]
		fp = flow.process
		p = q.popleft

		while q:
			fp(p(), source=self) # drain division queue for &flow

		# The availability of the flow allows the queue to be dropped.
		del self.div_queues[layer]
		if cflow == fc_terminate:
			flow.f_terminate(self)

	def div_transfer(self, fc, layer, subflow_transfer):
		"""
		# Enqueue or transfer the events to the flow associated with the layer context.
		"""

		flow = self.div_flows[layer] # KeyError when no FlowControl.initiate occurred.

		if flow is None:
			self.div_queues[layer].append(subflow_transfer)
			# block if overflow
		else:
			# Connected flow.
			flow.process(subflow_transfer, source=self)

	def div_overflow(self, fc, data):
		"""
		# Invoked when an upstream flow received data past a protocol's boundary.
		"""
		if not data:
			#
			pass
		else:
			if not hasattr(self, 'div_container_overflow'):
				self.div_container_overflow = []
			self.div_container_overflow.append(data)
		self.f_terminate()

	def div_terminate(self, fc, layer, fc_terminate=FlowControl.terminate):
		"""
		# End of Layer context content. Flush queue and remove entries.
		"""

		if layer in self.div_flows:
			flow = self.div_flows.pop(layer)
			if flow is None:
				# no flow connected, but expected to be.
				# just leave a note for .connect that it has been closed.
				self.div_flows[layer] = fc_terminate
			else:
				flow.f_ignore(self.f_obstruct, self.f_clear)
				flow.f_terminate(self)

			assert layer not in self.div_queues[layer]

	div_operations = {
		FlowControl.initiate: div_initiate,
		FlowControl.terminate: div_terminate,
		FlowControl.obstruct: None,
		FlowControl.clear: None,
		FlowControl.transfer: div_transfer,
		FlowControl.overflow: div_overflow,
	}

def Encoding(
		transformer,
		encoding:str='utf-8',
		errors:str='surrogateescape',

		gid=codecs.getincrementaldecoder,
		gie=codecs.getincrementalencoder,
	):
	"""
	# Encoding Transformation Generator.

	# Used with &Generator flows to create a transformation that performs
	# incremental encoding of &Flow throughput.
	"""

	emit = transformer.f_emit
	del transformer # don't hold the reference, we only need emit.
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

class Ports(Device):
	"""
	# Ports manages the set of listening sockets used by a &Unit.
	# Ports consist of a mapping of a set identifiers and the set of actual listening
	# sockets.

	# In addition to acquisition, &Ports inspects the environment for inherited
	# port sets. This is used to communicate socket inheritance across &/unix/man/2/exec calls.

	# The environment variables used to inherit interfaces across &/unix/man/2/exec
	# starts at &/env/FIOD_DEVICE_PORTS; it contains a list of slots used to hold the set
	# of listening sockets used to support the slot. Often, daemons will use
	# multiple slots in order to distinguish between secure and insecure.
	"""

	actuated = True
	terminated = False
	interrupted = False
	device_entry = 'ports'

	def structure(self):
		p = [
			('sets[%r]'%(sid,), binds)
			for sid, binds in self.sets.items()
		]
		sr = ()
		return (p, sr)

	def __init__(self):
		self.sets = collections.defaultdict(dict)

	def discard(self, slot):
		"""
		# Close the file descriptors associated with the given slot.
		"""

		close = os.close
		for k, fd in self.sets[slot].items():
			close(fd)

		del self.sets[slot]

	def bind(self, slot, *endpoints):
		"""
		# Bind the given endpoints and add them to the set identified by &slot.
		"""

		add = self.sets[slot].__setitem__

		# remove any existing file system sockets
		for x in endpoints:
			if x.protocol == 'local':
				if not x.route.exists():
					continue

				if x.route.type() == "socket":
					x.route.void()
				else:
					# XXX: more appropriate error
					raise RuntimeError("cannot overwrite file that is not a socket file")

		for ep, fd in zip(endpoints, self.context.bindings(*endpoints)):
			add(ep, fd)

	def close(self, slot, *endpoints):
		"""
		# Close the file descriptors associated with the given slot and endpoint.
		"""

		sd = self.sets[slot]

		for x in endpoints:
			fd = sd.pop(x, None)
			if fd is not None:
				os.close(fd)

	def acquire(self, slot:collections.abc.Hashable):
		"""
		# Acquire a set of listening &Transformer instances.
		# Each instance should be managed by a &Flow that constructs
		# the I/O &Transformer instances from the received socket connections.

		# Internal endpoints are usually managed as a simple transparent relay
		# where the constructed Relay instances are simply passed through.
		"""

		return self.sets[slot]

	def replace(self, slot, *endpoints):
		"""
		# Given a new set of interface bindings, update the slot in &sets so
		# they match. Interfaces not found in the new set will be closed.
		"""

		current_endpoints = set(self.sets[slot])
		new_endpoints = set(endpoints)

		delta = new_endpoints - current_endpoints
		self.bind(slot, *delta)

		current_endpoints.update(delta)
		removed = current_endpoints - new_endpoints
		self.close(slot, removed)

		return removed

	def load(self, route):
		"""
		# Load the Ports state from the given file.

		# Used by &.bin.rootd and &.bin.sectord to manage inplace restarts.
		"""

		with route.open('rb') as f:
			self.sets = pickle.load(f)

	def store(self, route):
		"""
		# Store the Ports state from the given file.

		# Used by &.bin.rootd and &.bin.sectord to manage inplace restarts.
		"""

		with route.open('wb') as f:
			pickle.dump(str(route), f)

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

def execute(*identity, **units):
	"""
	# Initialize a &system.Process to manage the invocation from the (operating) system.
	# This is the low-level means to invoke a &..io process from an executable module that
	# wants more control over the initialization process than what is offered by
	# &.command.

	# #!/pl/python
		libio.execute(unit_name = (unit_initialization,))

	# Creates a &Unit instance that is passed to the initialization function where
	# its hierarchy is then populated with &Sector instances.
	"""

	if identity:
		ident, = identity
	else:
		ident = 'root'

	sys_inv = process.Invocation.system() # Information about the system's invocation.

	spr = system.Process.spawn(sys_inv, Unit, units, identity=ident)
	# import root function
	process.control(spr.boot, ())

_parallel_lock = thread.amutex()
@contextlib.contextmanager
def parallel(*tasks, identity='parallel'):
	"""
	# Allocate a logical process assigned to the stack for parallel operation.
	# Primarily used by blocking programs looking to leverage &.io functionality.

	# A context manager that waits for completion in order to exit.

	# ! WARNING:
		# Tentative interface: This will be replaced with a safer implementation.
		# Concurrency is not properly supported and the shutdown process needs to be
		# handled gracefully.
	"""

	_parallel_lock.acquire()
	unit = None
	try:
		join = thread.amutex()
		join.acquire()

		inv = process.Invocation(lambda x: join.release())
		# TODO: Separate parallel's Process initialization from job dispatching.
		spr = system.Process.spawn(
			inv, Unit, {identity:tasks}, identity=identity,
			critical=functools.partial
		)
		spr.actuate()

		unit = spr.primary()
		# TODO: Yield a new root sector associated with the thread that spawned it.
		yield unit
	except:
		# TODO: Exceptions should interrupt the managed Sector.
		join.release()
		if unit is not None:
			unit.terminate()
		raise
	finally:
		join.acquire()
		_parallel_lock.release()
