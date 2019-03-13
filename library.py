"""
# Processor class hierarchy for managing explicitly structured processes.

# [ Properties ]
# /ProtocolTransactionEndpoint/
	# The typing decorator that identifies receivers
	# for protocol transactions. (Such as http requests or reponses.)
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
	'ip4': host.Endpoint.create_ip4,
	'ip6': host.Endpoint.create_ip6,
	'domain': host.Reference.from_domain,
}

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

from .core import Resource, Device, Processor, Sector, Scheduler, Recurrence
from .dispatch import Call, Coroutine, Thread, Subprocess
from .kills import Fatal

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
		from .flows import KInput, KOutput, Transports, Catenation, Division
		kin = KInput(transit[0])
		kout = KOutput(transit[1])

		ti, to = Transports.create(protocols)
		co = Catenation()
		di = Division()

		return (kin, ti, di, mitre, co, to, kout) # _flow input

	@staticmethod
	def _listen(transit):
		from .flows import KInput
		return KInput.sockets(transit)

	@staticmethod
	def _input(transit):
		from .flows import KInput
		return KInput(transit)

	@staticmethod
	def _output(transit):
		from .flows import KOutput
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

	# /xact_ctx_events/
		# Storage for initialization event completion, and
		# general storage area for the controlling &Transaction.

	# /xact_ctx_private/
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
	# A &Sector with Execution Context.

	# Transactions are sectors with a single &Context instance that is used to manage
	# the state of the Sector. Regular Sectors exit when all the processors are shutdown,
	# and Transactions do too. However, the &Context is the controlling processor and
	# must be the last to exit.

	# [ Properties ]

	# /xact_context/
		# The Processor that will be dispatched to initialize the Transaction
		# Sector and control its effect. Also, the receiver of &Processor.terminate.
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
		libkernel.execute(unit_name = (unit_initialization,))

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
