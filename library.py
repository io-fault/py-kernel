"""
Resources and Processor class hierarchy for managing explicitly structured processes.

[ Properties ]

/ProtocolTransactionEndpoint
	The typing decorator that identifies receivers
	for protocol transactions. (Such as http requests or reponses.)
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

from ..system import library as libsys
from ..system import libmemory

from ..routes import library as libroutes
from ..internet import libri
from ..internet import library as libnet
from ..chronometry import library as libtime
from ..computation import library as libc

from . import system

__shortname__ = 'libio'

#ref://reflectd.idx/index-entry?qtl=10#resolution.status.data
	#http://hostname/path/to/resource
		# qtl: Query Time Limit (seconds)
		#octets://gai.ai/domain.name?service=http&timeout|qtl=10#record-count-of-resolution

		#octets://v6.ip:80/::1#fd
		#octets://v4.ip:5555/127.0.0.1#fd
		#octets://v1-2.tls/context-name#<STATUS>, context
		#octets+flows://http/?constraints config [transformation]

		#octets://port.kernel/socket#fd
		#octets://port.kernel/input#fd
		#octets://port.kernel/output#fd

		#flows://v1-1.http/?constraints config [transformation]

		#flows://host/...

#...
	#octets://file.kernel/input (path)
	#octets://file.kernel/output/overwrite (path)
	#octets://file.kernel/output/append (path)

def parse_transport_indicator(ti:str, port = None):
	"""
	Parse a Transport Indicator for constructing connection templates.
	"""
	global libri
	parts = libri.parse(tri)

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

class Expiry(Exception):
	"""
	An operation exceeded a time limit.
	"""
	def __init__(self, constraint, timestamp):
		self.timestamp = timestamp
		self.constraint = constraint

class RateViolation(Expiry):
	"""
	The configured rate constraints could not be maintained.
	Usually a fault that identifies a Flow that could not maintain
	the minimum transfer rate.
	"""

class Lock(object):
	"""
	Event driven lock.

	Executes a given callback when it has been dequeued with the &release method
	as its parameter. When &release is then called by the lock's holder, the next
	enqueued callback is processed.
	"""
	__slots__ = ('_current', '_waiters',)

	def __init__(self, Queue = collections.deque):
		self._waiters = Queue()
		self._current = None

	def acquire(self, callback):
		"""
		Return boolean on whether or not it was **immediately** acquired.
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
		Returns boolean on whether or not the Switch was
		released **to another controller**.
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

def dereference_controller(self):
	return self.controller_reference()

def set_controller_reference(self, obj, Ref = weakref.ref):
	self.controller_reference = Ref(obj)

@functools.lru_cache(32)
def endpoint(type:str, address:str, port:object):
	"""
	Endpoint constructor for fault.io applicaitons.

	[ Samples ]

	/IPv4
		`libio.endpoint('ip4', '127.0.0.1', 80)`
	/IPv6
		`libio.endpoint('ip6', '::1', 80)`
	/UNIX
		`libio.endpoint('local', '/directory/path/to', 'socket_file')`
	"""

	global endpoint_classes
	return endpoint_classes[type](address, port)

def perspectives(resource, mro=inspect.getmro):
	"""
	Return the stack of structures used for Resource introspection.

	Traverses the MRO of the &resource class and executes the &structure
	method; the corresponding class, properties, and subresources are
	then appended to a list describing the &Resource from the perspective
	of each class.

	Returns `[(Class, properties, subresources), ...]`.
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
	Convert the structure tree of a &Resource into a sequence of tuples to be
	formatted for display.
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
	Format the &Resource tree in fault.text.
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
	Return the stack of controllers of the given &Resource. Excludes initial resource.
	"""

	stack = []
	obj = resource.controller

	while obj is not None:
		add(obj)
		obj = obj.controller

	return stack

class Local(tuple):
	"""
	A reference to a unix domain file system socket.
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
		return libroutes.File.from_absolute(self[0]) / self[1]

	@classmethod
	def create(Class, directory, file):
		return Class((directory, file))

	def __str__(self):
		return '[' + (self[0].rstrip('/') + '/') +self[1]+']'

class Coprocess(tuple):
	"""
	A reference to a coprocess interface. Used by &.libdaemon based processes
	in order to refer to each other.

	Used by distributed services in order to refer to custom listening interfaces.
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
	A process-local endpoint. These objects are pointers to [logical] process resources.
	"""

	__slots__ = ()
	protocol = 'rs' # Process[or Unit] Space

	@property
	def unit(self):
		"""
		The absolute unit name; &None if subjective reference.
		"""

		return self[0]

	@property
	def pid(self):
		"""
		The process identifier pointing to the location of the endpoint.
		Necessary in interprocess communication.
		"""

		return self[4]

	@property
	def path(self):
		"""
		The path in the structure used to locate the container.
		"""

		if not self.directory:
			return self[1][:-1]

	@property
	def identifier(self):
		"""
		Last component in the path if it's not a directory.
		"""

		if not self.directory:
			return self[1][-1]

	@property
	def directory(self):
		"""
		Endpoint refers to the *directory* of the location, not the assigned object.
		"""

		return self[2]

	@property
	def validation(self):
		"""
		A unique identifier selecting an object within the &Resource.
		Usually the result of an &id call of a particular object
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
		Parse an IRI-like indicator for selecting a process object.
		"""

		dir = False
		d = libri.parse(psi)

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
		Construct a local reference using the given absolute path.
		"""

		return Class((None, path, directory, None, None))

endpoint_classes = {
	'local': Local.create,
	'ip4': libnet.Endpoint.create_ip4,
	'ip6': libnet.Endpoint.create_ip6,
	'domain': libnet.Reference.from_domain,
	'internal': None, # relay push; local to process
	'coprocess': None, # process-group abstraction interface
}

class Join(object):
	"""
	An object whose purpose is to join the completion of multiple
	processors into a single event. Joins are used to simplify coroutines
	whose progression depends on a set of processors instead of one.

	Joins also enable interrupts to trigger completion events so that
	failures from unrelated Sectors can be communicated to callback.

	[ Properties ]

	/dependencies
		The original set of processors as a dictionary mapping
		given names to the corresponding &Processor.

	/pending
		The current state of pending exits that must
		occur prior to the join-operation's completion.

	/callback
		The callable that is performed after the &pending
		set has been emptied; defined by &atexit.
	"""

	__slots__ = ('dependencies', 'pending', 'callback')

	def __init__(self, **processors):
		"""
		Initialize the join with the given &processor set.
		"""

		self.dependencies = processors
		self.pending = set(processors.values())
		self.callback = None

	def connect(self):
		"""
		Connect the &Processor.atexit calls of the configured
		&dependencies to the &Join instance.
		"""

		for x in self.dependencies.values():
			x.atexit(self.exited)

		return self

	def __iter__(self, iter=iter):
		"""
		Return an iterator to the configured dependencies.
		"""

		return iter(self.dependencies.values())

	def __getitem__(self, k):
		"""
		Get the dependency the given identifier.
		"""

		return self.dependencies[k]

	def exited(self, processor):
		"""
		Record the exit of the given &processor and execute
		the &callback of the &Join if the &processor is the last
		in the configured &pending set.
		"""

		self.pending.discard(processor)

		if not self.pending:
			# join complete
			self.pending = None

			cb = self.callback
			self.callback = None; cb(self) # clear callback to signal completion

	def atexit(self, callback):
		"""
		Assign the callback of the &Join.

		If the &pending set is empty, the callback will be immediately executed,
		otherwise, overwrite the currently configured callback.

		The &callback is executed with the &Join instance as its sole parameter.

		[ Parameters ]

		/callback
			The task to perform when all the dependencies have exited.
		"""

		if self.pending is None:
			callback(self)
			return

		self.callback = callback

class ExceptionStructure(object):
	"""
	Exception associated with an interface supporting the sequencing of processor trees.
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
	A set of credentials and identities used by a &Sector to authorize actions by the entity.

	[ Properties ]

	/entity
		The identity of the user, person, bot, or organization that is being represented.
	/credentials
		The credentials provided to authenticate the user.
	/role
		An effective entity identifier; an override for entity.
	/authorization
		A set of authorization tokens for the systems that are being used by the entity.
	/device
		An identifier for the device that is being used to facilitate the connection.
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
	Base class for Layer Contexts

	[ Properties ]

	/(&bool)terminal
		Whether or not the Layer Context identifies itself as being
		the last to occur in a connection. Protocol routers use
		this to identify when to close input and output.

	/(&object)context
		The context of the layer. In cases of protocols that support
		multiple channels, the layer's context provides channel metadata
		so that transaction handlers can identify its source.
	"""

	context = None

class Resource(object):
	"""
	Base class for the Resource and Processor hierarchy making up a fault.io process.

	[ Properties ]

	/context
		The execution context that can be used to enqueue tasks,
		and provides access to the root &Unit.

	/controller
		The &Resource containing this &Resource.
	"""

	context = None
	controller_reference = lambda x: None

	controller = property(
		fget = dereference_controller,
		fset = set_controller_reference,
		doc = "Direct ascending resource containing this resource."
	)

	@property
	def unit(self):
		"""
		Return the &Unit that contains this &Resource instance.
		"""
		return self.context.association()

	@property
	def sector(self, isinstance=isinstance):
		"""
		Identify the &Sector holding the &Resource by scanning the &controller stack.
		"""

		global Sector

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
		Assign &ascent as the controller of &self and inherit its &Context.
		"""

		self.controller_reference = Ref(ascent)
		self.context = ascent.context

	def relocate(self, ascent):
		"""
		Relocate the Resource into the &ascent Resource.

		Primarily used to relocate &Processors from one sector into another.
		Controller resources may not support move operations; the origin
		location must support the erase method and the destination must
		support the acquire method.
		"""

		controller = self.controller
		ascent.acquire(self)
		controller.eject(self)

	def structure(self):
		"""
		Returns a pair, a list of properties and list of subresources.
		Each list contains pairs designating the name of the property
		or resource and the object itself.

		The structure method is used for introspective purposes and each
		implementation in the class hierarchy will be called (&sequence) in order
		to acquire a reasonable representation of the Resource's contents.

		Implementations are used by &format and &sequence.
		"""

		return None

class Device(Resource):
	"""
	A resource that is loaded by &Unit instances into (io.resource)`/dev`

	Devices often have special purposes that regular &Resource instances do not
	normally fulfill. The name is a metaphor for operating system kernel devices
	as they are often associated with kernel features.
	"""

	@classmethod
	def connect(Class, unit):
		"""
		Load an instance of the &Device into the given &unit.
		"""

		dev = Class()
		unit.place(dev, 'dev', Class.device_entry)
		dev.subresource(unit)

		return dev

@collections.abc.Awaitable.register
class Processor(Resource):
	"""
	A resource that maintains an abstract computational state. Processors are
	awaitable and can be used by coroutines. The product assigned to the
	Processor is the object by await.

	Processor resources essentially manage state machines and provide an
	abstraction for initial and terminal states that are often used.

	Core State Transition Sequence.

		# Instantiate
		# Actuate
		# Functioning
		# Terminating
		# Terminated
		# Interrupted

	Where the functioning state designates that the implementation specific state
	has been engaged. Often, actuation and termination intersect with implementation states.

	The interrupted state is special; its used as a frozen state of the machine and is normally
	associated with an exception. The term interrupt is used as it is nearly analogous with UNIX
	process interrupts (unix.signal)`SIGINT`.
	"""

	actuated = False
	terminated = False
	terminating = None # None means there is no terminating state.
	interrupted = False

	terminator = None
	interruptor = None

	product = None
	exceptions = None

	# Only used by processor groupings.
	exit_event_connections = None

	@property
	def functioning(self):
		"""
		Whether or not the Processor is functioning.

		Indicates that the processor was actuated and is neither terminated nor interrupted.

		! NOTE:
			Processors are functioning *during* termination; instances where
			`Processor.terminating == True`.
			Termination may cause limited access to functionality, but
			are still considered functional.
		"""

		return self.actuated and not (self.terminated or self.interrupted)

	def controlled(self, subprocessor):
		"""
		Whether or not the given &Processor is directly controlled by &self.
		"""

		# Generic Processor has no knowledge of subresources.
		return False

	def requisite(self):
		"""
		Configure any necessary requisites prior to actuation.
		Preferred over creation arguments in order to allow the use of prebuilt structures.

		Subclasses should not call superclass implementations; rather, users of complex
		implementations need to be aware that multiple requisite invocations will be necessary
		in order for actuation to succeed.

		Base class &requisite is a no-op.
		"""

		pass

	def actuate(self):
		"""
		Note the processor as actuated by setting &actuated to &True.
		"""

		self.actuated = True
		return self

	def process(self, event):
		"""
		Base class implementation merely discarding the event.

		Subclasses may override this to formally support messaging.
		"""

		pass

	def terminate(self, by=None):
		"""
		Note the Processor as terminating.
		"""

		if not self.functioning or self.terminating:
			return False

		self.terminating = True
		self.terminator = by
		return True

	def interrupt(self, by=None):
		"""
		Note the processor as being interrupted.

		Subclasses must perform any related resource releases after
		calling the superclass's implementation.

		Only &Sector interrupts cause exits.
		"""

		if self.interrupted:
			return False

		self.interruptor = by
		self.interrupted = True
		return True

	def fault(self, exception, association=None):
		"""
		Note the given exception as an error on the &Processor.

		Exceptions identified as errors cause the &Processor to exit.
		"""

		if self.exceptions is None:
			self.exceptions = set()

		self.exceptions.add((association, exception))
		self.context.faulted(self)

	def _fio_fault_trap(self, trapped_task):
		try:
			trapped_task() # Executed relative to &Sector instance.
		except BaseException as exc:
			self.fault(exc)

	def ctx_enqueue_task(self, task, partial=functools.partial, trap=_fio_fault_trap):
		"""
		Enqueue a task associated with the sector so that exceptions cause the sector to
		fault. This is the appropriate way for &Processor instances controlled by a sector
		to sequence processing.
		"""
		self.context.enqueue(partial(trap, self, task))
	del _fio_fault_trap

	def atexit(self, exit_callback):
		"""
		Register a callback to be executed when the Processor has been unlinked from
		the Resource hierarchy.

		The given callback is called after termination is complete and the Processor's
		reference has been released by the controller. However, the controller backref
		should still be available at this time.

		The callback is registered on the *controlling resource* which must be a &Processor.

		The &exit_callback will **not** be called if the &Processor was interrupted.
		"""

		if self.terminated:
			exit_callback(self) # Processor already exited.
		else:
			self.controller.exit_event_connect(self, exit_callback)

	def final(self):
		"""
		Identify the &Processor as being final in that the exit of the processor
		causes the sector to *terminate*. The &Sector will, in turn, invoke termination
		on the remaining processors and exit when all of the processors have exited.
		"""
		self.controller.final = self
		self.atexit(lambda final: final.controller.terminate())

	def __await__(self):
		"""
		Coroutine interface support. Await the exit of the processor.
		Awaiting the exit of a processor will never raise exceptions with
		exception to internal (Python) errors. This is one of the notable
		contrasts between Python's builtin Futures and fault.io Processors.
		"""

		# Never signalled.
		if not self.terminated:
			yield self
		return self.product

	def exit_event_connect(self, processor, callback, dict=dict):
		"""
		Connect the given callback to the exit of the given processor.
		The &processor must be controlled by &self and any necessary
		data structures will be initialized.
		"""

		assert processor.controller is self

		eec = self.exit_event_connections
		if eec is None:
			eec = self.exit_event_connections = dict()

		cbl = eec.get(processor, ())
		eec[processor] = cbl + (callback,)

	def exit_event_disconnect(self, processor, callback):
		l = list(self.exit_event_connections[processor])
		l.remove(callback)
		if not l:
			del self.exit_event_connections[processor]
		else:
			self.exit_event_connections[processor] = tuple(l)

	def exit_event_emit(self, processor, partial=functools.partial):
		"""
		Called when an exit occurs to emit exit events to any connected callbacks.
		"""

		eec = self.exit_event_connections
		if eec is not None:
			self.context.enqueue(*[partial(x, processor) for x in eec.pop(processor, ())])
			if not eec:
				del self.exit_event_connections

	def structure(self):
		"""
		Provides the structure stack with at-exit callbacks.
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
				('interruptor', self.interruptor),
			] if x[1] is not None
		]
		props.extend(p)

		return (props, sr)

	def placement(self):
		"""
		Define the set index to use when dispatched by a &Sector.

		By default, &Sector instances place &Processor instances into
		&set objects that stored inside a dictionary. The index used
		for placement is allowed to be overridden in order to optimize
		the groups and allow better runtime introspection.
		"""

		return self.__class__

	def substitute(self, processor):
		"""
		Terminate the processor &self, but reassign the exit hooks to be performed
		when the given &processor exits. &processor will be dispatched into the controlling
		sector.
		"""
		raise NotImplemented

class Call(Processor):
	"""
	A single call represented as a Processor.

	The callable is executed by process and signals its exit after completion.

	Used as an abstraction to explicit enqueues, and trigger faults in Sectors.
	"""

	@classmethod
	def partial(Class, call:collections.abc.Callable, *args, **kw):
		"""
		Create a call applying the arguments to the callable upon actuation.
		The positional arguments will follow the &Sector instance passed as
		the first argument.
		"""
		global functools
		return Class(functools.partial(call, *args, **kw))

	def __init__(self, call:functools.partial):
		"""
		The partial application to the callable to perform.
		Usually, instantiating from &partial is preferrable;
		however, given the presence of a &functools.partial instance,
		direct initialization is better.

		[ Parameters ]
		/call
			The callable to enqueue during actuation of the &Processor.
		"""
		self.source = call

	def actuate(self):
		self.ctx_enqueue_task(self.execution)
		return super().actuate()

	def execution(self, event=None, source=None):
		assert self.functioning

		try:
			self.product = self.source() # Execute Callable.
			self.terminated = True
			self.controller.exited(self)
		except BaseException as exc:
			self.product = None
			self.fault(exc)

	def structure(self):
		return ([('source', self.source)], ())

class Coroutine(Processor):
	"""
	Processor for coroutines.

	Manages the generator state in order to signal the containing &Sector of its
	exit. Generator coroutines are the common method for serializing the dispatch of
	work to relevant &Sector instances.
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
		! INTERNAL:
			Private Method.

		Container for the coroutine's execution in order
		to map completion to processor exit.
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
		Start the coroutine.
		"""

		state = self.container()
		self.unit.stacks[self] = state

		super().actuate()
		self.enqueue(state.send)

	def terminate(self):
		"""
		Force the coroutine to close.
		"""
		if not super().terminate():
			return False
		self.state.close()
		return True

	def interrupt(self):
		self.state.throw(KeyboardInterrupt)

class Unit(Processor):
	"""
	An asynchronous logical process. Unit instances are the root level objects
	associated with the &Process instance. There can be a set of &Unit instances
	per process, but usually only one exists.

	Units differ from most &Processor classes as it provides some additional
	interfaces for managing exit codes and assigned standard I/O interfaces
	provided as part of the system process.

	Units are constructed from a set of roots that build out the &Sector instances
	within the runtime tree which looks similar to an in memory filesystem.
	"""

	@staticmethod
	def _connect_subflows(mitre, transit, *protocols):
		kin = KernelPort(transit[0])
		kout = KernelPort(transit[1])

		ti, to = Transports.create(protocols)
		fi = Transformation(*meter_input(kin), ti)
		fo = Transformation(to, *meter_output(kout))
		co = Catenation()
		di = Division()

		return (fi, di, mitre, co, fo) # _flow input

	@staticmethod
	def _listen(transit):
		kin = KernelPort(transit)
		fi = Transformation(*meter_input(kin, allocate=Allocator.allocate_integer_array))

		return fi

	@staticmethod
	def _input(transit):
		kin = KernelPort(transit)
		fi = Transformation(*meter_input(kin))

		return fi

	@staticmethod
	def _output(transit):
		kout = KernelPort(transit)
		fo = Transformation(*meter_output(kout))

		return fo

	@property
	def ports(self):
		"""
		(io.location)`/dev/ports` accessor
		"""

		return self.u_index[('dev','ports')]

	@property
	def scheduler(self):
		"""
		(io.location)`/dev/scheduler` accessor
		"""

		return self.u_index[('dev','scheduler')]

	def load_ports_device(self):
		"""
		Load the &Ports 'device'. Usually used by daemon processes.
		"""

		ports = Ports()
		self.place(ports, 'dev', 'ports')
		ports.subresource(self)

	def device(self, entry:str):
		"""
		Return the device resource placed at the given &entry.
		"""

		return self.u_index.get(('dev', entry))

	@property
	def faults(self):
		"""
		The (rt:path)`/dev/faults` resource.
		"""
		return self.device('faults')

	def faulted(self, resource:Resource, path=None) -> None:
		"""
		Place the sector into the faults directory using the hex identifier
		as its name.

		If the path, a sequence of strings, is provided, qualify the identity
		with the string representation of the path, `'/'.join(path)`.
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

	def __init__(self):
		"""
		Initialze the &Unit instance with the an empty hierarchy.

		&Unit instances maintain state and it is inappropriate to call
		the initialization function during its use. New instances should
		always be created.
		"""
		global Libraries
		super().__init__()

		self.identity = self.identifier = None
		self.libraries = Libraries(self)
		self.u_exit = set()
		self.u_faults = dict()

		# total index; tuple -> sector
		self.u_index = dict()
		self.u_reverse_index = dict()

		self.u_roots = []

		# tree containing sectors; navigation access
		self.u_hierarchy = dict(
			bin = dict(), # Sectors that determine Unit's continuation
			lib = dict(), # Library Sectors; terminated when bin/ is empty.
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
		Ran to finish &Unit initialization; extends the sequences of roots used
		to initialize the root sectors.
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
		Add a callback to be executed *prior* to the Unit exiting.
		"""
		self.u_exit.add(callback)

	def exited(self, processor:Processor):
		"""
		Processor exit handler. Register faults and check for &Unit exit condition.
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
		Execute the Unit by enqueueing the initialization functions.

		This should only be called by the controller of the program.
		Normally, it is called automatically when the program is loaded by the process.
		"""
		global Scheduler
		super().actuate()

		# Allows the roots to perform scheduling.
		scheduler = Scheduler()
		scheduler.subresource(self)
		self.place(scheduler, 'dev', 'scheduler')
		scheduler.actuate()

		self.place(self.context.process, 'dev', 'process')

		for sector_init in self.u_roots:
			sector_init(self)

	def link(self, **paths):
		"""
		Link a set of libraries into the &Unit.
		"""

		for libname, route in paths.items():
			continue # Ignore libraries for the time being.
			lib = Library(route)
			self.place(lib, 'lib', libname)
			lib.subresource(self)
			lib.actuate()

	def terminate(self):
		global __process_index__

		if self.terminated is not True:
			if self.context.process.primary() is self:
				if self.u_hierarchy['faults']:
					self.context.process.report()
				self.context.process.terminate(getattr(self, 'result', 0))
				self.terminated = True
			else:
				self.terminated = True

	def place(self, obj:collections.abc.Hashable, *destination):
		"""
		Place the given resource in the process unit at the specified location.
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
		Remove a &Sector from the index and tree.
		"""

		obj = self.u_index[address]
		del self.u_reverse_index[obj]
		del self.u_index[address]

	def listdir(self, *address, list=list):
		"""
		List the contents of an address.
		This only includes subdirectories.
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
		Send an overview of the logical process state to the given target.
		"""

		global format
		target.writelines(x+'\n' for x in format(self.identity, self))
		target.write('\n')
		target.flush()

class Sector(Processor):
	"""
	A processing sector; manages a set of &Processor resources according to their class.
	Termination of a &Sector is solely dependent whether or not there are any
	&Processor instances within the &Sector.

	Sectors are the primary &Processor class and have protocols for managing projections
	of entities (users) and their authorizing credentials.

	[ Properties ]

	/projection
		Determines the entity that is being represented by the process.

	/processors
		A divided set of abstract processors currently running within a sector.
		The sets are divided by their type inside a &collections.defaultdict.

	/scheduler
		The Sector local schduler instance for managing recurrences and alarms
		configured by subresources. The exit of the Sector causes scheduled
		events to be dismissed.

	/exits
		Set of Processors that are currently exiting.
		&None if nothing is currently exiting.
	"""

	projection = None

	scheduler = None
	exits = None
	processors = None
	product = None

	def structure(self):
		if self.projection is not None:
			p = [('projection', self.projection)]
		else:
			p = ()

		sr = [
			(hex(id(x)), x)
			for x in itertools.chain.from_iterable(self.processors.values())
		]

		return (p, sr)

	def __init__(self, *processors, Processors=functools.partial(collections.defaultdict,set)):
		super().__init__()

		# Ready the processors for actuation.
		sprocs = self.processors = Processors()
		for proc in processors:
			sprocs[proc.__class__].add(proc)
			proc.subresource(self)

	def actuate(self):
		"""
		Actuate the Sector by actuating its processors.
		There is no guarantee to the order in which the controlled
		processors are actuated.

		Exceptions that occur during actuation fault the Sector causing
		the *controlling sector* to exit. If faults should not cause
		the parent to be interrupted, they *must* be dispatched after
		&self has been actuated.
		"""

		try:
			for Class, sset in list(self.processors.items()):
				for proc in sset:
					proc.actuate()
		except BaseException as exc:
			self.fault(exc)

		return super().actuate()

	def scheduling(self):
		"""
		Initialize the &scheduler for the &Sector.
		"""
		global Scheduler
		self.scheduler = Scheduler()
		self.scheduler.subresource(self)
		self.scheduler.actuate()

	def eject(self, processor):
		"""
		Remove the processor from the Sector without performing termination.
		Used by &Resource.relocate.
		"""

		self.processors[processor.__class__].discard(processor)

	def acquire(self, processor):
		"""
		Add a process to the Sector; the processor is assumed to have been actuated.
		"""

		processor.subresource(self)
		self.processors[processor.__class__].add(processor)

	def process(self, events):
		"""
		Load the sequence of &Processor instances into the Sector and actuate them.
		"""

		structs = self.processors

		for ps in events:
			structs[ps.__class__].add(ps)
			ps.subresource(self)
			ps.actuate()

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
			self.controller.exited(self)
			self.terminated = True
			self.terminating = False

		return True

	def interrupt(self, by=None):
		"""
		Interrupt the Sector by interrupting all of the subprocessors.
		The order of interruption is random, and *should* be insignificant.
		"""

		if self.interrupted:
			return

		super().interrupt(by)

		if self.scheduler is not None:
			self.scheduler.interrupt()

		for Class, sset in self.processors.items():
			for x in sset:
				x.interrupt()

		# exits are managed by the invoker

	def exited(self, processor, set=set):
		"""
		Sector structure exit handler.
		"""

		if self.exits is None:
			self.exits = set()
			self.context.enqueue(self.reap)

		self.exits.add(processor)

	def dispatch(self, processor:Processor):
		"""
		Dispatch the given &processor inside the Sector.
		Assigns the processor as a subresource of the
		instance, affixes it, and actuates it.

		Returns the result of actuation, the &processor.
		"""

		processor.subresource(self)
		self.processors[processor.placement()].add(processor)
		processor.actuate()

		return processor

	def coroutine(self, gf):
		"""
		Dispatches an arbitrary coroutine returning function as a &Coroutine instance.
		"""

		global Coroutine
		gc = Coroutine.from_callable(gf)
		self.processors[Coroutine].add(gc)
		gc.subresource(self)

		return gc.actuate()

	def flow(self, *sequences, chain=itertools.chain):
		"""
		Create a flow and designate the sequences of Transformers
		as its requisites (pipeline).

		Each argument must be sequences of transformers.
		"""

		global Transformation
		f = Transformation(*chain(*sequences))
		self.dispatch(f)

		return f

	def _flow(self, series):
		# XXX: Replace .flow() or create a more stable access point. (implicit or explicit)
		self.process(series)

		x = series[0]
		for n in series[1:]:
			x.f_connect(n)
			x = n

	def reap(self, set=set):
		"""
		Empty the exit set and check for sector completion.
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
		Called once the set of exited processors has been reaped
		in order to identify if the Sector should notify the
		controlling Sector of an exit event..
		"""

		# reap/reaped is not used in cases of interrupts.
		if not self.processors and not self.interrupted:
			# no processors remain; exit Sector
			self.terminated = True
			self.terminating = False

			if self.scheduler is not None:
				# After termination has been completed, the scheduler can be stopped.
				#
				# The termination process is an arbitrary period of time
				# that may rely on the scheduler, so it is important
				# that this is performed here.
				self.scheduler.interrupt()

			controller = self.controller
			if controller is not None:
				controller.exited(self)

	def placement(self):
		"""
		Use &Interface.if_sector_placement if the sector has an Interface.
		Otherwise, &Sector.
		"""
		global Interface
		for if_proc in self.processors.get(Interface, ()):
			# Use the interface processor's definition if any.
			return if_proc.sector_placement()
		else:
			return self.__class__

class Extension(Sector):
	"""
	A &Sector that extends the containing &Sector so that faults are inherited by
	the container. Faults that occur in extensions of extensions are inherited by
	a responsible &Sector instance.
	"""

	def fault(self, exception, association=None):
		"""
		Assign the exception and fault the responsible &Sector.
		"""
		global SectorExtension

		if self.exceptions is None:
			self.exceptions = set()

		self.exceptions.add((association, exception))

		x = self.controller
		while isinstance(x, SectorExtension):
			x = x.controller

		self.context.faulted(trapping_sector) # fault occurred inside extension

class Subprocess(Processor):
	"""
	A Processor that represents a *set* of Unix subprocesses.
	Primarily exists to map process exit events to processor exits and
	management of subprocessor metadata such as the Process-Id of the child.
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
		The exit event of the only Process-Id. &None or the pair (pid, exitcode).
		"""

		for i in self.process_exit_events:
			return i, self.process_exit_events.get(i)

		return None

	def sp_exit(self, pid, event):
		self.process_exit_events[pid] = event
		self.active_processes.discard(pid)

		if not self.active_processes:
			del self.active_processes
			self.terminated = True
			self.terminating = None

			self.product = len(self.process_exit_events)

			# Don't exit if interrupted; maintain position in hierarchy.
			if not self.interrupted:
				self.controller.exited(self)

	def sp_signal(self, signo, send_signal=os.kill):
		"""
		Send the given signal number (os.kill) to the active processes
		being managed by the instance.
		"""
		for pid in self.active_processes:
			send_signal(pid, signo)
	signal = sp_signal # REMOVE

	def signal_process_group(self, signo, send_signal=os.kill):
		"""
		Like &signal, but send the signal to the process group instead of the exact process.
		"""
		for pid in self.active_processes:
			send_signal(-pid, signo)

	def actuate(self):
		"""
		Initialize the system event callbacks for receiving process exit events.
		"""

		proc = self.context.process
		callback = self.sp_exit

		# Track it first.
		for pid in self.active_processes:
			proc.system_event_connect(('process', pid), self, callback)
			proc.kernel.track(pid)

		# Validate that the process exists; it may have exited before .track() above.
		finished = False
		while not finished:
			try:
				for pid in self.active_processes:
					os.kill(pid, 0)
				else:
					finished = True
			except OSError as err:
				if err.errno != os.ESRCH:
					raise
				proc.system_event_disconnect(('process', pid))
				self.sp_exit(pid, libsys.process_delta(pid))

		return super().actuate()

	def terminate(self, by=None, signal=15):
		if not self.terminating:
			super().terminate(by=by)
			self.signal(signal)

	def interrupt(self, by=None):
		# System Events remain connected; still want sp_exit.
		super().interrupt(by)
		self.signal(9)

class Recurrence(Processor):
	"""
	Timer maintenance for recurring tasks.

	Usually used for short term recurrences such as animations and human status updates.
	"""

	def __init__(self, target):
		self.target = target

	def actuate(self):
		"""
		Enqueue the initial execution of the recurrence.
		"""

		super().actuate()
		self.context.enqueue(self.occur)

	def occur(self):
		"""
		Invoke a recurrence and use its return to schedule its next iteration.
		"""

		if self.terminating:
			self.terminated = True
			self.sector.exited(self)
		else:
			next_delay = self.target()
			if next_delay is not None:
				self.controller.scheduler.defer(next_delay, self.occur)

class Scheduler(Processor):
	"""
	Delayed execution of arbitrary callables.

	Manages the set alarms and &Recurrence's used by a &Sector.
	Normally, only one Scheduler exists per and each &Scheduler
	instance chains from an ancestor creating a tree of heap queues.
	"""

	scheduled_reference = None
	x_ops = None
	# XXX: need proper weakref handling of scheduled tasks

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

		return super().actuate()

	@staticmethod
	def execute_weak_method(weakmethod):
		return weakmethod()()

	def update(self):
		"""
		Update the scheduled transition callback.
		"""

		# Method is being passed to ancestor, so use weakmethod.

		nr = weakref.WeakMethod(self.transition)
		if self.scheduled_reference is not None:
			self.x_ops[1](self.scheduled_reference)

		sr = self.scheduled_reference = functools.partial(self.execute_weak_method, nr)
		self.x_ops[0](self.state.period(), sr)

	def schedule(self, pit:libtime.Timestamp, *tasks, now=libtime.now):
		"""
		Schedule the &tasks to be executed at the specified Point In Time, &pit.
		"""

		measure = now().measure(pit)
		return self.defer(measure, *tasks)

	def defer(self, measure, *tasks):
		"""
		Defer the execution of the given &tasks by the given &measure.
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
		Cancel the execution of the given task scheduled by this instance.
		"""

		self.state.cancel(task)

	def recurrence(self, callback):
		"""
		Allocate a &Recurrence and dispatch it in the same &Sector as the &Scheduler
		instance. The target will be executed immediately allowing it to identify
		the appropriate initial delay.
		"""

		r = Recurrence(callback)
		self.controller.dispatch(r)
		return r

	def transition(self):
		"""
		Execute the next task given that the period has elapsed.
		If the period has not elapsed, reschedule &transition in order to achieve
		finer granularity.
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
				self.fault(scheduling_exception)

	def process(self, event, Point=libtime.core.Point, Measure=libtime.core.Measure):
		"""
		Schedule the set of tasks.
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

	def interrupt(self, by=None):
		# cancel the transition callback
		if self.scheduled_reference is not None:
			self.x_ops[1](self.scheduled_reference)

		super().interrupt(by)

class Libraries(object):
	"""
	Interface object for accessing &Unit libraries.

	Provides attribute based access to the set of libraries and a method to load new ones.
	"""

	__slots__ = ('_unit', '_access')

	def __init__(self, unit, Ref=weakref.ref):
		self._unit = Ref(unit)
		self._access = dict()

	def __getattr__(self, attr):
		if attr not in self._access:
			u = self._unit()

			try:
				sector = u.index[('lib', attr)]
			except KeyError:
				raise AttributeError(attr)

			r = self._access[attr] = sector.api()
		else:
			r = self._access[attr]

		return r

class Thread(Processor):
	"""
	A &Processor that runs a callable in a dedicated thread.
	"""

	@classmethod
	def queueprocessor(Class):
		raise NotImplementedError
		t = Class()
		t.requisite(self._queue_process)

	def requisite(self, callable):
		self.callable = callable

	def __init__(self, callable):
		self.callable = callable

	def trap(self):
		final = None
		try:
			self.callable(self)
			self.terminated = True
			self.terminating = False
			# Must be enqueued to exit.
			final = functools.partial(self.controller.exited, self)
		except Exception as exc:
			final = functools.partial(self.fault, exc)

		self.context.enqueue(final)

	def actuate(self):
		"""
		Execute the dedicated thread for the transformer.
		"""
		super().actuate()
		self.context.execute(self, self.trap)
		return self

	def process(self):
		"""
		No-op as the thread exists to emit side-effects.
		"""
		pass

class Interface(Processor):
	"""
	A &Processor that is identified as a source of work for the process.
	Significant in that, if all &Interface instances are terminated, the process
	itself should eventually terminate as well.
	"""

	def placement(self):
		"""
		Returns &Interface. Constant placement for subclasses so
		that &Interface instances may be quickly identified in &Sector processor sets.
		"""
		global Interface
		return Interface

class System(Interface):
	"""
	An Interface used to manage the set of system listening interfaces and
	connect accept events to an appropriate handler. The interface actuates
	by creating the &Terminal and the connecting source flows that allocate
	sockets.

	[ Properties ]

	/if_slot
		The set of interfaces that will source connections to be processed by
		this interface.
	"""

	if_slot = None

	def structure(self):
		p = [
			('if_slot', self.if_slot),
		]
		return (p, ())

	def __init__(self, mitre, ref, router, transports, slot=None):
		"""
		Select the &Ports slot to acquire listening sockets from.

		[ Parameters ]

		/slot
			The slot to acquire from the &Ports instance assigned to "/dev/ports".
		"""
		super().__init__()
		self.if_transports = transports
		self.if_slot = slot

		self.if_mitre = mitre
		self.if_reference = ref
		self.if_router = router

	def actuate(self):
		global null, Sockets
		super().actuate()

		alloc = Allocator.allocate_integer_array
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
		Callback ran when the sockets sector exits.

		This handles cases where all the listening sockets are closed.
		"""
		pass

	def if_spawn_connections(self, packet,
			chain=itertools.chain.from_iterable,
		):
		"""
		Spawn connections from the socket file descriptors sent from the upstream.

		[ Parameters ]

		/packet
			The sequence of sequences containing Kernel Port references (file descriptors).
		/transports
			The transport layers to configure &Transports transformers with.

		[ Effects ]

		Dispatches &Connection instances associated with the accepted file descriptors
		received from the upstream.
		"""
		global endpoint
		sector = self.controller
		ctx_accept = self.context.accept_subflows

		source, event = packet
		for fd in chain(event):
			mitre = self.if_mitre(self.if_reference, self.if_router)
			series = ctx_accept(fd, mitre, mitre.Protocol())
			cxn = Sector()
			sector.dispatch(cxn) # actuate and assign the connection
			cxn._flow(series)
			series[0].process(None) # fix. actuation or Flow.f_initiate()

class Transformer(Resource):
	"""
	A Transformer is a unit of state that produces change in a Flow.

	[ Properties ]

	/retains
		Whether or not the Transformer holds events for some purpose.
		Essentially used to communicate whether or not &drain performs
		some operation.
	"""

	retains = False

	def inject(self, event):
		"""
		Inject an event after the &Transformer's position in the &Flow.
		"""
		self.f_emit(event)

	def process(self, event):
		raise NotImplementedError(
			"transformer subclass (%s) did not implement process" %(self.__class__.__name__,)
		)

	def actuate(self):
		pass

	def f_emit(self, event):
		raise RuntimeError("emit property was not initialized to the following transformer")

	def drain(self):
		pass

	def terminate(self):
		pass

	def interrupt(self):
		pass

class Reflection(Transformer):
	"""
	Transformer that performs no modifications to the processed events.

	Reflections are Transformers that usually create some side effect based
	on the processed events.
	"""

	process = Transformer.inject

class Transports(Transformer):
	"""
	Transports represents a stack of protocol layers and manages their
	initialization and termination so that the outermost layer is
	terminated before the inner layers, and vice versa for initialization.

	Transports are primarily used to manage protocol layers like TLS where
	the flows are completely dependent on the &Transports.

	[ Properties ]
	/t_termination_index
		Not Implemented.

		/(&int)`x > 0`
			The lowest index of the stack that has terminated
			in both directions. When &t_termination_index is equal
			to `1`, the pair of transports will reach a terminated
			state.
		/&None
			No part of the stack has terminated.

	/polarity
		/`-1`
			The transport is sending events out.
		/`+1`
			The transport is receiving events in.

	/operations
		The operations used to apply the layers for the respective direction.

	/operation_set
		Class-wide dictionary containing the functions
		needed to resolve the transport operations used by a layer.
	"""

	operation_set = dict()
	@classmethod
	def create(Class, transports, Stack=list):
		"""
		Create a pair of &Transports instances.
		"""
		global weakref

		i = Class(1)
		o = Class(-1)

		i.opposite_transformer = weakref.ref(o)
		o.opposite_transformer = weakref.ref(i)

		stack = i.stack = o.stack = Stack(transports)

		ops = [
			Class.operation_set[x.__class__](x) for x in stack
		]
		i.operations = [x[0] for x in ops]

		# Output must reverse the operations in order to properly
		# layer the transports.
		o.operations = [x[1] for x in ops]
		o.operations.reverse()

		return (i, o)

	polarity = 0 # neither input nor output.
	def __init__(self, polarity:int):
		self.polarity = polarity
		self.t_termination_index = None

	def __repr__(self, format="<{path} [{stack}]>"):
		path = self.__class__.__module__.rsplit('.', 1)[-1]
		path += '.' + self.__class__.__qualname__
		return format.format(path=path, stack=repr(self.stack))

	@property
	def opposite(self):
		"""
		The transformer of the opposite direction for the Transports pair.
		"""
		return self.opposite_transformer()

	drain_cb = None
	def drained(self):
		drain_cb = self.drain_cb
		if not self.stack:
			flow = self.controller
			if flow.terminating:
				# terminal drain
				pass

		if drain_cb is not None:
			del self.drain_cb
			drain_cb()

	def drain(self):
		"""
		Drain the transport layer.

		Buffers are left as empty as possible, so flow termination is the only
		condition that leaves a requirement for drain completion.
		"""

		if self.stack:
			# Only block if there are items on the stack.
			flow = self.controller
			if not flow.terminating and flow.functioning:
				# Run empty process to flush.
				self.process(())
				return None
			else:
				# Terminal Drain.
				if flow.f_permanent:
					# flow is permanently obstructed and transfers
					# are irrelevant at one level or another
					# so try to process whatever is available, finish
					# the drain operation so termination can finish.
					self.process(())
					# If a given Transports side is dead, so is the other.
					self.opposite.closed()

					# If it's permanent, no drain can be performed.
					return None
				else:
					# Signal transport that termination needs to occur.
					self.stack[-1].terminate(self.polarity)
					# Send whatever termination signal occurred.
					flow.context.enqueue(self.empty)

					return functools.partial(self.__setattr__, 'drain_cb')
		else:
			# No stack, not draining.
			pass

		# No stack or not terminating.
		return None

	def closed(self):
		# Closing the transport layers is closing
		# the actual transport. This is how Transports()
		# distinguishes itself from protocol managed layers.

		self.drained()

		flow = self.controller

		# If the flow isn't terminating, then it was
		# the remote end that caused the TL to terminate.
		# In which case, the flow needs to be terminated by Transports.
		if not flow.interrupted and not flow.terminated:
			# Initiate termination.
			# If called here, the drain() won't block on Transports.
			flow.terminate(by=self)

	def empty(self):
		self.process(())

	def terminal(self):
		self.process(())
		if not self.stack[-1].terminated:
			o = self.opposite
			of = o.controller
			if of.terminating and of.functioning:
				# Terminate other side if terminating and functioning.
				self.stack[-1].terminate(-self.polarity)
				o.process(())

	def process(self, events):
		if not self.operations:
			# Opposite cannot have work if empty.
			self.f_emit(events) # Empty transport stack acts a passthrough.
			return

		opposite_has_work = False

		for ops in self.operations:
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
			# from a poorly written stack entry.
			self.opposite.process(())

		stack = self.stack

		if stack and stack[-1].terminated:
			# *fully* terminated. pop item after allowing the opposite to complete

			# This needs to be done as the transport needs the ability
			# to flush any remaining events in the opposite direction.
			opp = self.opposite

			del stack[-1] # both sides; stack is shared.

			# operations is perspective sensitive
			if self.polarity == 1:
				# recv/input
				del self.operations[-1]
				del opp.operations[0]
			else:
				# send/output
				del self.operations[0]
				del opp.operations[-1]

			if stack:
				if self.controller.terminating:
					# continue termination.
					self.stack[-1].terminate(self.polarity)
					self.controller.context.enqueue(self.terminal)
			else:
				self.closed()
				self.opposite.closed()

	def terminate(self):
		flow = self.controller

		if flow.f_permanent and self.stack:
			self.stack[-1].terminate(self.polarity)

		for x in list(self.stack):
			self.empty()

class Reactor(Transformer):
	"""
	A Transformer that is sensitive to Flow obstructions.

	Reactors are distinct from Transformers in that they automatically receive obstruction
	notifications in order to relay failures to dependencies that fall outside the &Flow.

	Installation into A &Flow causes the &suspend and &resume methods to be called whenever the
	&Flow is obstructed or cleared. Subclasses are expected to override them in order
	to handle the signals.
	"""

	def actuate(self):
		super().actuate()
		self.controller.f_watch(self.suspend, self.resume)

	def suspend(self, flow):
		"""
		Method to be overridden for handling Flow obstructions.
		"""
		pass

	def resume(self, flow):
		"""
		Method to be overridden for handling Flow clears.
		"""
		pass

class Parallel(Transformer):
	"""
	A dedicated thread for a Transformer.
	Usually used for producing arbitrary injection events produced by blocking calls.

	Term Parallel being used as the actual function is ran in parallel to
	the &Flow in which it is participating in.

	The requisite function should have the following signature:

	#!/pl/python
		def thread_function(transformer, queue, *optional):
			...

	The queue provides access to the events that were received by the Transformer,
	and the &transformer argument allows the thread to cause obstructions by
	accessing its controller.

	! DEVELOPER:
		Needs better drain support. Currently,
		terminal drains are hacked on and regular drains
		not are supported.
	"""
	def requisite(self, thread:typing.Callable, *parameters, criticial=False):
		self.thread = thread
		self.parameters = parameters

	def drain(self):
		"""
		Wait for thread exit if terminating.

		Currently does not block if it's not a terminal drain.
		"""

		if self.controller.terminating:
			self.put(None)
			return self.atshutdown

	callbacks = None
	def completion(self):
		if self.callbacks:
			for drain_complete_r in self.callbacks:
				drain_complete_r()
			del self.callbacks

	def atshutdown(self, callback):
		if self.callbacks is None:
			self.callbacks = set()

		self.callbacks.add(callback)

	def trap(self):
		"""
		Internal; Trap exceptions in order to map them to faults.
		"""

		try:
			self.thread(self, self.queue, *self.parameters)
			self.controller.context.enqueue(self.completion)
		except BaseException as exc:
			self.controller.context.enqueue(functools.partial(self.fault, exc))
			pass # The exception is managed by .fault()

	def actuate(self):
		"""
		Execute the dedicated thread for the transformer.
		"""
		global queue

		self.queue = queue.Queue()
		self.put = self.queue.put
		self.process = self.put

		#self.context.execute(self, self.callable, *((self, self.queue) + self.parameters))
		self.controller.context.execute(self, self.trap)

		return super().actuate()

	def process(self, event):
		"""
		Send the event to the queue that the Thread is connected to.
		Injections performed by the thread will be enqueued into the main task queue.
		"""

		self.put(event)

class KernelPort(Transformer):
	"""
	Transformer moving received events through a transit and back into the
	flow that the Loop is participating in.
	"""

	def __init__(self, transit=None):
		self.transit = transit
		self.acquire = transit.acquire
		transit.link = self
		#transit.resize_exoresource(1024*128)

	def __repr__(self):
		c = self.__class__
		mn = c.__module__.rsplit('.', 1)[-1]
		qn = c.__qualname__

		if self.transit:
			port, ep = self.transit.port, self.transit.endpoint()
		else:
			port, ep = self.status

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

	def actuate(self):
		self.process = self.transit.acquire
		self.controller.context._sys_traffic_attach(self.transit)

	def transition(self):
		# Called when the resource was exhausted
		# Unused atm and pending deletion.
		pass

	def terminate(self):
		"""
		Called by the controlling &Flow, acquire status information and
		unlink the transit.
		"""
		if self.transit is not None:
			t = self.transit
			self.transit = None
			self.status = (t.port, t.endpoint())
			t.link = None # signals I/O loop to not inject.
			t.terminate() # terminates one direction.
	interrupt = terminate

	def terminated(self):
		# THIS METHOD IS NOT CALLED IF TERMINATE/INTERRUPT() WAS USED.

		# Called when the termination condition is received,
		# but *after* any transfers have been injected.

		# io.traffic calls this when it sees termination of the transit.

		if self.transit is None:
			# terminate has already been ran; status is present
			pass
		else:
			flow = self.controller
			t = self.transit
			t.link = None
			self.transit = None
			self.status = (t.port, t.endpoint())

			# Exception is not thrown as the transport's error condition
			# might be irrelevant to the success of the application.
			# If a transaction was successfully committed and followed
			# with a transport error, it's probably appropriate to
			# show the transport issue, if any, as a warning.
			flow.f_obstruct(self, None, Inexorable)
			flow.terminate(self)

	def process(self, event):
		# This method is actually overwritten on actuate.
		# process is set to Transit.acquire.
		self.transit.acquire(event)

class Functional(Transformer):
	"""
	A transformer that emits the result of a provided function.
	"""

	def __init__(self, transformation:collections.abc.Callable):
		self.transformation = transformation

	def actuate(self, compose=libc.compose):
		self.process = compose(self.f_emit, self.transformation)

	def process(self, event):
		self.f_emit(self.transformation(event))

	@classmethod
	def generator(Class, generator):
		"""
		Create a functional transformer using a generator.
		"""

		next(generator)
		return Class(generator.send)

	@classmethod
	def chains(Class, depth=1, chain=itertools.chain.from_iterable):
		"""
		Create a transformer wrapping a events in a composition of chains.
		"""
		return Class.compose(list, *([chain]*depth))

	@classmethod
	def compose(Class, *sequence, Compose=libc.compose):
		"""
		Create a function transformer from a composition.
		"""
		return Class(Compose(*sequence))

class Meter(Reactor):
	"""
	Base class for constructing meter Transformers.

	Meters are used to measure throughput of a Flow. Primarily used
	in conjunction with a sensor to identify when a Detour has finished
	transferring data to the kernel.

	Meters are also Reactors; they manage obstructions in order to control
	the Flow given excessive resource usage.
	"""

	def __init__(self):
		super().__init__()
		self.transferring = None
		self.transferred = 0
		self.total = 0

	measure = len

	def transition(self, len=len, StopIteration=StopIteration):
		# filter empty transfers
		measure = 0

		try:
			alloc = self.next()
		except StopIteration as exc:
			self.controller.terminate(by=exc)
			self.transferring = 0
			return

		measure = self.transferring = self.measure(alloc)
		self.transferred = 0

		self.f_emit(alloc)

	def exited(self, event):
		# Called by the Sensor.

		for x in event:
			m = self.measure(x)
			self.transferred += m
			self.total += m

		if self.transferring is None or self.transferred == self.transferring:
			self.transferred = 0
			self.transferring = None
			self.transition()

class Allocator(Meter):
	"""
	Transformer that continually allocates memory for the downstream Transformers.

	Used indirectly by &KernelPort instances that reference an input transit.
	"""

	allocate_integer_array = (array.array("i", [-1]).__mul__, 24)
	allocate_byte_array = (bytearray, 1024*4)

	def __init__(self, allocate=allocate_byte_array):
		super().__init__()
		self.allocate = allocate
		self.resource_size = allocate[1]

		self.obstructed = False # the *controller* is being arbitrary obstructed
		self.transitioned = False

	def transition(self):
		"""
		Transition in the next buffer provided that the Flow was not obstructed.
		"""

		if not self.obstructed:
			super().transition()
		else:
			self.transitioned = True

	def next(self):
		return self.allocate[0](self.resource_size)

	def process(self, events):
		assert events is None
		self.transition()

	def resume(self, flow):
		"""
		Continue allocating memory for &KernelPort transformers.
		"""

		self.obstructed = False
		if self.transitioned:
			self.transitioned = False
			super().transition()

	def suspend(self, flow):
		# It mostly waits for resume events to make a decision
		# about what should be done next.
		self.obstructed = True

class Throttle(Meter):
	"""
	Transformer that buffers received events until it is signalled that they may be processed.

	The queue is limited to a certain number of items rather than a metadata constraint;
	for instance, the sum of the length of the buffer entries. This allows the connected
	Flows to dynamically choose the buffer size by adjusting the size of the events.
	"""

	limit = 16
	retains = True # Throttle manages the drain.
	draining = False

	def __repr__(self):
		qlen = len(self.queue)
		qsize = sum(map(len, self.queue))
		bufsize = self.transferring
		xfer = self.transferred

		s = "<%s q:%r items %r length; buf: %r of %r at %s; total: %r>" %(
			self.__class__.__name__,
			qlen, qsize, xfer, bufsize,
			hex(id(self)),
			self.total
		)

		return s

	@property
	def overflow(self):
		"""
		Queue entries exceeds limit.
		"""
		return len(self.queue) > self.limit

	def __init__(self, Queue=collections.deque):
		super().__init__()
		self.queue = Queue()
		self.next = self.queue.popleft
		self.obstructing = False # *this* transformer is obstructing

	def transition(self):
		# in order for a drain to be complete, we must transition on an empty queue.
		if self.queue:
			# pop
			super().transition()
		else:
			if self.draining is not False:
				self.draining()
				del self.draining # become class defined False

		if self.obstructing and not self.queue:
			self.obstructing = False
			self.controller.f_clear(self)

	def drain(self):
		if self.queue or self.transferring is not None and self.controller.f_permanent == False:
			return functools.partial(self.__setattr__, 'draining')
		else:
			# queue is empty
			return None

	def suspend(self, flow):
		if flow.terminated:
			return

		if flow.f_permanent and self.draining is not False:
			# the flow was permanently obstructed during
			# a drain operation, which means the throttle
			# needs to eject any transfers and release
			# the drain lock.
			drained_cb = self.draining
			del self.draining
			drained_cb()

	def process(self, event, len=len):
		"""
		Enqueue a sequence of events for processing by the following Transformer.
		"""

		self.queue.extend(event)

		if self.transferring is None:
			# nothing transferring, so there should be no transfer resources (Transit/Detour)
			self.transition()
		else:
			global Condition
			if len(self.queue) > self.limit:
				self.obstructing = True
				self.controller.f_obstruct(self, None,
					Condition(self, ('overflow',))
				)

def meter_input(ix, allocate=Allocator.allocate_byte_array):
	"""
	Create the necessary Transformers for metered input.
	"""
	global Allocator, Trace

	meter = Allocator(allocate)
	cb = meter.exited
	trace = Trace()
	trace.monitor("xfer-completion", cb)

	return (meter, ix, trace)

def meter_output(ox):
	"""
	Create the necessary Transformers for metered output.
	"""
	global Throttle, Trace

	meter = Throttle()
	cb = meter.exited
	trace = Trace()
	trace.monitor("xfer-completion", cb)
	return (meter, ox, trace)

class Condition(object):
	"""
	A *reference* to a logical expression or logical function.

	Conditional references are constructed from a subject object, attribute path, and parameters.
	Used to clearly describe the objects that participate in a logical conclusion of interest.

	Used by &Flow instances to describe the condition in which an obstruction is removed.
	Conditions provide introspecting utilities the capacity to identify the cause of
	an obstruction.
	"""

	__slots__ = ('focus', 'path', 'parameter')

	def __init__(self, focus, path, parameter = None):
		"""
		[Parameters]

		/focus
			The root object that is safe to reference
		/path
			The sequence of attributes to resolve relative to the &focus.
		/parameter
			Determines the condition is a method and should be given this
			as its sole parameter. &None indicates that the condition is a property.
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
		global Inexorable
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
	Signal objects used to communicate flow control operations
	for subflow management. These objects are used by &Catenation and &Distribution
	to index operations.
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
	A Processor consisting of an arbitrary set of operations that
	can connect to other &Flow instances in order to make a series
	of transformations.

	Flows are the primary mechanism used to stream events; generally,
	anything that's a stream should be managed by &Flow instances in favor
	of other event callback mechanisms.

	[ Properties ]
	/f_type
		The flow type describing what the instance does.
		This property can be &None at the class level, but should be initialized
		when an instance is created.

		/(id)`source`
			Flow produces events, but does not process them.
		/(id)`terminal`
			Flow processes events, but emits nothing.
		/(id)`switch`
			Flow that takes events and distributes their transformation
			to a mapping of receiving flows. (Diffusion)
		/(id)`join`
			Flow that receives events from a set of sources and combines
			them into a single stream.
		/(id)`transformer`
			Flow emits events strictly in response to processing. Transformers
			may buffer events as needed.
		/&None
			Unspecified type.

	/f_obstructions
		/&None
			No obstructions present.
		/&typing.Mapping
			The objects that are obstructing the &Flow from
			performing processing associated with the exact
			condition causing it.

	/f_monitors
		The set of callbacks used to signal changes in the flow's
		&f_obstructed state.

		/&None
			No monitors watching the flow state.

	/f_downstream
		The &Flow instance that receives events emitted by the instance
		holding the attribute.
	"""

	terminating = False
	terminated = False

	f_type = None
	f_obstructions = None
	f_monitors = None
	f_downstream = None

	def f_connect(self, flow:Processor, partial=functools.partial):
		"""
		Connect the Flow to the given object supporting the &Flow interface.
		Normally used with other Flows, but other objects may be connected.

		Downstream is *not* notified of upstream obstructions. Events run
		downstream and obstructions run up.
		"""
		if self.f_downstream:
			self.f_disconnect()

		# Downstreams do not need to be notified of upstream obstructions.
		# Even with output rate constraints, there is no need to apply
		# constraints if the write buffer is usually empty.

		# Events run downstream, obstructions run upstream.

		self.f_downstream = flow
		flow.f_watch(self.f_obstruct, self.f_clear)
		self.f_emit = flow.process
	connect = f_connect

	def f_disconnect(self):
		"""
		Disconnect from the downstream and cease emitting events into &f_downstream.
		"""
		flow = self.f_downstream
		del self.f_downstream
		flow.f_ignore(self.f_obstruct, self.f_clear)
		self.controller.exit_event_disconnect(self, flow.terminate)
		del self.f_emit

	def __repr__(self):
		return '<' + self.__class__.__name__ + '[' + hex(id(self)) + ']>'

	def structure(self):
		"""
		Reveal the obstructions and monitors of the Flow.
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
		Actuate the Transformers placed in the Flow by &requisite.
		If the &Flow has been connected to another, actuate the &downstream
		as well.
		"""
		super().actuate()

		if self.f_downstream:
			self.f_downstream.actuate()

	def terminate(self, by=None):
		"""
		Drain the Flow and finish termination by signalling the controller
		of its exit.
		"""

		if self.terminated or self.terminating or self.interrupted:
			return False

		self.terminator = by
		self.terminating = True

		self.ctx_enqueue_task(self._f_terminated)
		return True

	def _f_terminated(self):
		"""
		Used by subclasses to issue downstream termination and exit.

		Subclasses must call this or perform equivalent actions when termination
		is complete.
		"""

		self.process = self.f_discarding
		self.f_emit = self.f_discarding

		self.terminated = True
		self.terminating = False

		if self.f_downstream:
			self.f_downstream.terminate(by=self)

		if self.controller:
			self.controller.exited(self)

	def interrupt(self, by=None):
		"""
		Terminate the flow abrubtly.
		"""
		if not super().interrupt(by):
			return False

		self.process = self.f_discarding
		self.f_emit = self.f_discarding

		if self.f_downstream:
			# interrupt the downstream and
			# notify exit iff the downstream's
			# controller is functioning.
			ds = self.f_downstream
			ds.terminate(self)
			dsc = ds.controller
			if dsc is not None and dsc.functioning:
				dsc.exited(ds)

		return True

	def process(self, event, source=None):
		"""
		Emit the &event directly to the downstream.
		"""
		self.f_emit(event, source=self)

	def f_emit(self, event, source=None):
		"""
		Method replaced at runtime for selecting the recipient
		of a processed event.
		"""
		pass

	@property
	def f_obstructed(self):
		"""
		Whether or not the &Flow is obstructed.
		"""

		return self.f_obstructions is not None

	@property
	def f_permanent(self, sum=sum) -> int:
		"""
		Whether or not there are Inexorable obstructions present.
		An integer specifying the number of &Inexorable obstructions or &None
		if there are no obstructions.
		"""

		global Inexorable
		if self.f_obstructions:
			return sum([1 if x[1] is Inexorable else 0 for x in self.f_obstructions.values()])

	def f_obstruct(self, by, signal=None, condition=None):
		"""
		Instruct the Flow to signal the cessation of transfers.
		The cessation may be permanent depending on the condition.
		"""
		global Inexorable

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
		Clear the obstruction by the key given to &obstruction.
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
		Assign the given functions as callbacks to obstruction events.
		First called when an obstruction occurs and second when its cleared.
		"""

		if self.f_monitors is None:
			self.f_monitors = set()
		self.f_monitors.add((obstructed, cleared))

		if self.f_obstructed:
			obstructed(self)

	def f_ignore(self, obstructed, cleared):
		"""
		Stop watching the Flow's obstructed state.
		"""

		self.f_monitors.discard((obstructed, cleared))

	def f_discarding(self, event, source = None):
		"""
		Assigned to &process and &f_emit after termination and interrupt in order
		to keep overruns from exercising the Transformations.
		"""

		pass

class Mitre(Flow):
	"""
	The joining flow between input and output.

	Subclasses of this flow manage the routing of protocol requests.
	"""
	f_type = 'mitre'

	def f_connect(self, flow:Processor):
		"""
		Connect the given flow as downstream without inheriting obstructions.
		"""

		# Similar to &Flow, but no obstruction events.
		self.f_downstream = flow
		self.f_emit = flow.process
		self.atexit(flow.terminate)

class Sockets(Mitre):
	"""
	Mitre for transport flows created by &System in order to accept sockets.
	"""
	def __init__(self, reference, router):
		self.m_reference = reference
		self.m_router = router

	def process(self, event, source=None):
		"""
		Accept the event, but do nothing as Terminals do not propogate events.
		"""
		update = self.m_router((self.m_reference, event))
		if update:
			self.m_router = update

	def atexit(self, receiver):
		if receiver != self.f_downstream.terminate:
			# Sockets() always sends to null, don't bother with a atexit entry.
			return super().atexit(receiver)

class Iteration(Flow):
	"""
	Flow that emits the contents of an &collections.abc.Iterator until
	an obstruction occurs or the iterator ends.
	"""
	f_type = 'source'

	def f_clear(self, *args) -> bool:
		"""
		Override of &Flow.f_clear that enqueues an &it_transition call
		if it's no longer obstructed.
		"""

		if super().f_clear(*args):
			self.ctx_enqueue_task(self.it_transition)
			return True
		return False

	def it_transition(self):
		"""
		Emit the next item in the iterator until an obstruction occurs or
		the iterator is exhausted.
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
		[ Parameters ]

		/iterator
			The iterator that produces events.
		"""

		self.it_iterator = iter(iterator)

	def actuate(self):
		super().actuate()
		if not self.f_obstructed:
			self.ctx_enqueue_task(self.it_transition)

	def process(self, it, source=None):
		"""
		Raises exception as &Iteration is a source.
		"""
		raise Exception('Iteration only produces')

class Collection(Flow):
	"""
	Terminal &Flow collecting the events into a buffer for processing after
	termination.
	"""
	f_type = 'terminal'

	def __init__(self, storage, operation):
		super().__init__()
		self.c_storage = storage
		self.c_operation = operation

	@classmethod
	def list(Class):
		"""
		Construct a &Collection instance that appends all events into a &list
		instance.
		"""
		l = []
		return Class(l, l.append)

	@classmethod
	def dict(Class, initial=None):
		"""
		Construct a &Collection instance that builds the contents of a
		mapping from sequences of key-value pairs.
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
		Construct a &Collection instance that accumulates data from sequences
		of data into a single &bytearray.
		"""
		if initial is None:
			initial = bytearray()
		return Class(initial, partial(Class._buffer_operation, barray=initial))

	def process(self, obj, source=None):
		self.c_operation(obj)

class Transformation(Flow):
	"""
	A Processor consisting of a sequence of transformations.
	The &Transformer instances may cause side effects in order
	to perform kernel I/O or inter-Sector communication.

	Flows are the primary mechanism used to stream events; generally,
	anything that's a stream should be managed by &Flow instances in favor
	of other event callback mechanisms.

	! DEVELOPER:
		Flow termination starts with a terminal drain;
		the Flow is obstructed, a drain operation is initiated.
		Completion of the drain causes the finish() method to be called
		to run the terminate() methods on the transformers.
		Once the transformers are terminated, the Flow exits.
	"""
	draining = False

	@classmethod
	def construct(Class, controller, *calls):
		"""
		Construct the Flow from the Transformers created by the &calls
		after noting it as a subresource of &controller.

		The returned &Flow instance will not yet be actuated.
		"""

		f = Class()
		f.subresource(controller)
		controller.requisite(f)
		f.requisite(*[c() for c in calls])

		return f

	def __repr__(self):
		links = ' -> '.join(['[%s]' %(repr(x),) for x in self.xf_sequence])
		return '<' + self.__class__.__name__ + '[' + hex(id(self)) + ']: ' + links + '>'

	def structure(self):
		"""
		Reveal the Transformers as properties.
		"""

		sr = ()
		s = self.xf_sequence
		p = [(i, s[i]) for i in range(len(s))]

		return (p, sr)

	xf_sequence = ()
	def __init__(self, *transformers):
		"""
		Construct the transformer sequence defining the flow.
		"""

		super().__init__()
		for x in transformers:
			x.subresource(self)

		transformers[-1].f_emit = self.emission # tie the last to Flow's emit

		self.xf_sequence = transformers

	def actuate(self):
		"""
		Actuate the Transformers placed in the Flow by &requisite.
		If the &Flow has been connected to another, actuate the &downstream
		as well.
		"""

		emit = self.emission
		for transformer in reversed(self.xf_sequence):
			transformer.f_emit = emit
			transformer.actuate()
			emit = transformer.process

		super().actuate()

	def drain(self, callback=None):
		"""
		Drain all the Transformers in the order that they were affixed.

		Drain operations implicitly obstruct the &Flow until it's complete.
		The obstruction is used because the operation may not be able to complete
		if events are being processed.

		Returns boolean; whether or not a new drain operation was started.
		&False means that there was a drain operation in progress.
		&True means that a new drain operation was started.
		"""

		if self.draining is not False and callback:
			self.draining.add(callback)
			return False
		else:
			self.draining = set()

			if callback is not None:
				self.draining.add(callback)

			if not self.terminating:
				# Don't obstruct if terminating.
				clear_when = Condition(self, ('draining',))
				self.f_obstruct(self.__class__.drain, None, clear_when)

			# initiate drain
			return self.drains(0)

	def drains(self, index, arg=None, partial=functools.partial):
		"""
		! INTERNAL:
			Drain state callback.

		Maintains the order of transformer drain operations.
		"""

		for i in range(index, len(self.xf_sequence)):
			xf = self.xf_sequence[i]
			rcb = xf.drain()
			if rcb is not None:
				# callback registration returned, next drain depends on this
				rcb(partial(self.drains, i+1))
				return False
			else:
				# drain complete, no completion continuation need take place
				# continue processing transformers
				pass
		else:
			# drain complete
			for after_drain_callback in self.draining:
				after_drain_callback()

			del self.draining # not draining
			if not self.terminating and not self.terminated:
				self.f_clear(self.__class__.drain)

		return True

	def finish(self):
		"""
		Internal method called when a terminal drain is completed.

		Called after a terminal &drain to set the terminal state..
		"""
		global Inexorable
		assert self.terminating is True

		self.terminated = True
		self.terminating = False
		self.process = self.f_discarding

		for x in self.xf_sequence:
			# signal terminate.
			x.terminate()

		if self.f_downstream:
			self.f_downstream.terminate(by=self)

		self.f_obstruct(self.__class__.terminate, None, Inexorable)

		self.controller.exited(self)

	def terminate(self, by=None):
		"""
		Drain the Flow and finish termination by signalling the controller
		of its exit.
		"""
		if self.terminated or self.terminating or self.interrupted:
			return False

		self.terminator = by
		self.terminated = False
		self.terminating = True

		self.drain(self.finish) # set the drainage obstruction

		return True

	def interrupt(self, by=None):
		"""
		Terminate the flow abrubtly inhibiting *blocking* drainage of Transformers.
		"""

		if self.interrupted:
			return False

		super().interrupt(by)
		self.process = self.f_discarding

		for x in self.xf_sequence:
			x.interrupt()

		if self.f_downstream:
			# interrupt the downstream and
			# notify exit iff the downstream's
			# controller is functioning.
			ds = self.f_downstream
			ds.interrupt(self)
			dsc = ds.controller
			if dsc.functioning:
				dsc.exited(ds)

	def process(self, event, source = None):
		"""
		Place the event into the flow's transformer sequence.

		&process takes an additional &source parameter for maintaining
		the origin of an event across tasks.
		"""

		self.xf_sequence[0].process(event)

	def continuation(self, event, source = None):
		"""
		Receives events from the last Transformer in the sequence.
		Defaults to throwing the event away, but overridden when
		connected to another flow.
		"""

		# Overridden when .emit is set.
		pass

	def emission(self, event):
		return self.continuation(event, source = self) # identify flow as source

	def _emit_manager():
		# Internal; property managing the emission of the &Flow

		def fget(self):
			if self.xf_sequence:
				# emit of the last transformer poitns to edge of flow
				return self.emission
			else:
				return None

		def fset(self, val):
			# given that IO is inserted into a flow
			self.continuation = val

		def fdel(self):
			# rebind continuation
			self.continuation = self.__class__.continuation

		doc = "Properly manage the emit setting at the end of a flow instance."
		return locals()
	f_emit = property(**_emit_manager())

ProtocolTransactionEndpoint = typing.Callable[[
	Processor, Layer, Layer, typing.Callable[[Flow], None]
], None]

class Null(Flow):
	"""
	Flow that has no controller, ignores termination, and emits no events.

	Conceptual equivalent of (system:filepath)`/dev/null`.
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
		Induces termination in downstream.
		"""
		downstream.terminate(by=self)

	def f_watch(*args):
		pass
	def f_ignore(*args):
		pass

	def terminate(self, by=None):
		pass
	def interrupt(self, by=None):
		pass
	def process(self, event, source=None):
		pass
null = Null()

class Funnel(Flow):
	"""
	A union of events that emits data received from a set of &Transformation instances.

	Funnels receive events from a set of &Transformation instances and map the
	&Transformation to a particular
	identifier that can be used by the downstream Transformers.

	Funnels will not terminate when connected upstreams terminate.
	"""

	def terminate(self, by=None):
		global Flow

		if not isinstance(by, Flow):
			# Termination induced by flows are ignored.
			super().terminate(by=by)

class Trace(Reflection):
	"""
	Reflection that allows a set of operations to derive meta data from the Transformation.
	"""

	def __init__(self):
		super().__init__()
		self.monitors = dict()

	def monitor(self, identity, callback):
		"""
		Assign a monitor to the Meta Reflection.

		[ Parameters ]

		/identity
			Arbitrary hashable used to refer to the callback.

		/callback
			Unary callable that receives all events processed by Trace.
		"""

		self.monitors[identity] = callback

	def trace_process(self, event):
		for x in self.monitors.values():
			x(event)

		self.f_emit(event)
	process = trace_process

	@staticmethod
	def log(event, title=None, flush=sys.stderr.flush, log=sys.stderr.write):
		"""
		Trace monitor for printing events.
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
	Sequence a set of flows in the enqueued order.

	Emulates parallel operation by facilitating the sequenced delivery of
	a sequence of flows where the first flow is carried until completion before
	the following flow may be processed.

	Essentially, this is a buffer array that uses Flow termination signals
	to manage the current working flow and queues to buffer the events to be emitted.

	[ Untested ]

		- Recursive transition() calls.

	[ Properties ]

	/cat_order
		Queue of &Layer instances dictating the order of the flows.
	/cat_connections
		Mapping of connected &Flow instances to their corresponding
		queue, &Layer, and termination state.
	/cat_flows
		Connection identifier mapping to a connected &Flow.
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
		Whether the given flow's queue has too many items.
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
		Emit point for Sequenced Flows
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

	def terminate(self, by=None):
		cxn = self.cat_connections.get(by)

		if cxn is None:
			# Not termination from a connection.
			# Note as terminating.
			if self.terminating:
				return False
			self.terminating = True
			self.terminator = by
			self.cat_flush()
			return True

		q, layer, term = cxn

		if layer == self.cat_order[0]:
			# Head of line.
			self.cat_transition()
		else:
			# Not head of line. Update entry's termination state.
			self.cat_connections[by] = (q, layer, True)

		return False

	def cat_flush(self):
		"""
		Flush the accumulated events downstream.
		"""
		events = self.cat_events
		self.cat_events = [] # Reset before emit in case of re-enqueue.
		self.f_emit(events, self)

		if self.terminating is True and len(self.cat_order) == 0:
			# No reservations in a terminating state finishes termination.
			self._f_terminated()

	def cat_reserve(self, layer):
		"""
		Reserve a position in the sequencing of the flows. The given &layer is the reference
		object used by &cat_connect in order to actually connect flows.
		"""

		self.cat_order.append(layer)

	def cat_connect(self, layer, flow, fc_init=FlowControl.initiate, Queue=collections.deque):
		"""
		Connect the flow to the given layer signalling that its ready to process events.
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
		Drain the new head of line emitting any queued events and
		updating its entry in &cat_connections to immediately send events.
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
		Move the first enqueued flow to the front of the line;
		flush out the buffer and remove ourselves as an obstruction.
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
	Coordination of the routing of a protocol's layer content.

	Protocols consisting of a series of requests, HTTP for instance,
	need to control where the content of a request goes. &QueueProtocolInput
	manages the connections to actual &Flow instances that delivers
	the transformed application level events.
	"""
	f_type = 'fork'

	def __init__(self):
		global collections

		super().__init__()
		self.div_queues = collections.defaultdict(collections.deque)
		self.div_flows = dict() # connections
		self.div_initiations = []

	def process(self, events, source=None):
		"""
		Direct the given events to their corresponding action in order to
		map protocol stream events to &Flow instances.
		"""
		ops = self.div_operations.__getitem__
		for event in events:
			ops(event[0])(self, *event)

		if self.div_initiations:
			# Aggregate initiations for single propagation.
			self.f_emit(self.div_initiations)
			self.div_initiations = []

	def interrupt(self, by=None, fc_terminate=FlowControl.terminate):
		"""
		Interruptions on distributions translates to termination.
		"""

		if not super().interrupt(by=by):
			return False

		# Any connected div_flows are subjected to interruption here.
		# Closure here means that the protocol state did not manage
		# &close the transaction and we need to assume that its incomplete.
		for layer, flow in self.div_flows.items():
			if flow in {fc_terminate, None}:
				continue
			flow.terminate(by=self)

		return True

	def div_initiate(self, fc, layer, getattr=getattr, partial=functools.partial):
		"""
		Initiate a subflow using the given &layer as its identity.
		The &layer along with a callable performing &div_connect will be emitted
		to the &Flow.f_connect downstream.
		"""

		self.div_flows[layer] = None
		connect = partial(self.div_connect, layer)

		# Note initiation and associate connect callback.
		self.div_initiations.append((layer, connect))

	def div_connect(self, layer:Layer, flow:Flow, fc_terminate=FlowControl.terminate):
		"""
		Associate the &flow with the &layer allowing transfers into the flow.

		Drains the queue that was collecting events associated with the &layer,
		and feeds them into the flow before destroying the queue. Layer connections
		without queues are the head of the line, and actively receiving transfers
		and control events.
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
			flow.terminate(by=self)

	def div_transfer(self, fc, layer, subflow_transfer):
		"""
		Enqueue or transfer the events to the flow associated with the layer context.
		"""

		flow = self.div_flows[layer] # KeyError when no FlowControl.initiate occurred.

		if flow is None:
			self.div_queues[layer].append(subflow_transfer)
			# block if overflow
		else:
			# Connected flow.
			flow.process(subflow_transfer, source=self)

	def div_terminate(self, fc, layer, fc_terminate=FlowControl.terminate):
		"""
		End of Layer context content. Flush queue and remove entries.
		"""

		if layer in self.div_flows:
			flow = self.div_flows.pop(layer)
			if flow is None:
				# no flow connected, but expected to be.
				# just leave a note for .connect that it has been closed.
				self.div_flows[layer] = fc_terminate
			else:
				flow.f_ignore(self.f_obstruct, self.f_clear)
				flow.terminate(self)

			assert layer not in self.div_queues[layer]

	div_operations = {
		FlowControl.initiate: div_initiate,
		FlowControl.terminate: div_terminate,
		FlowControl.obstruct: None,
		FlowControl.clear: None,
		FlowControl.transfer: div_transfer,
	}

def Encoding(
		transformer,
		encoding:str='utf-8',
		errors:str='surrogateescape',

		gid=codecs.getincrementaldecoder,
		gie=codecs.getincrementalencoder,
	):
	"""
	Encoding Transformation Generator.

	Used with &Generator Transformers to create Transformers that perform
	incremental decoding or encoding of &Flow throughput.
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
	Ports manages the set of listening sockets used by a &Unit.
	Ports consist of a mapping of a set identifiers and the set of actual listening
	sockets.

	In addition to acquisition, &Ports inspects the environment for inherited
	port sets. This is used to communicate socket inheritance across &/unix/man/2/exec calls.

	The environment variables used to inherit interfaces across &/unix/man/2/exec
	starts at &/env/FIOD_DEVICE_PORTS; it contains a list of slots used to hold the set
	of listening sockets used to support the slot. Often, daemons will use
	multiple slots in order to distinguish between secure and insecure.
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
		self.users = {}

	def discard(self, slot):
		"""
		Close the file descriptors associated with the given slot.
		"""

		close = os.close
		for k, fd in self.sets[slot].items():
			close(fd)

		del self.sets[slot]

	def bind(self, slot, *endpoints):
		"""
		Bind the given endpoints and add them to the set identified by &slot.
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
					raise Exception("cannot overwrite file that is not a socket file")

		for ep, fd in zip(endpoints, self.context.bindings(*endpoints)):
			add(ep, fd)

	def close(self, slot, *endpoints):
		"""
		Close the file descriptors associated with the given slot and endpoint.
		"""

		sd = self.sets[slot]

		for x in endpoints:
			fd = sd.pop(x, None)
			if fd is not None:
				os.close(fd)

	def acquire(self, slot:collections.abc.Hashable):
		"""
		Acquire a set of listening &Transformer instances.
		Each instance should be managed by a &Flow that constructs
		the I/O &Transformer instances from the received socket connections.

		Internal endpoints are usually managed as a simple transparent relay
		where the constructed Relay instances are simply passed through.
		"""

		return self.sets[slot]

	def associate(self, slot, processor):
		"""
		Associate a slot with a particular processor in order to document
		the user of the slot.
		"""

		self.users[slot] = processor

	def replace(self, slot, *endpoints):
		"""
		Given a new set of interface bindings, update the slot in &sets so
		they match. Interfaces not found in the new set will be closed.
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
		Load the Ports state from the given file.

		Used by &.bin.rootd and &.bin.sectord to manage inplace restarts.
		"""

		with route.open('rb') as f:
			self.sets = pickle.load(f)

	def store(self, route):
		"""
		Store the Ports state from the given file.

		Used by &.bin.rootd and &.bin.sectord to manage inplace restarts.
		"""

		with route.open('wb') as f:
			pickle.dump(str(route), f)

def context(max_depth=None):
	"""
	Finds the &Processor instance that caused the function to be invoked.

	Used to discover the execution context when it wasn't explicitly
	passed forward.
	"""
	global sys

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
	Execute a &..system.library.KPipeline object building an IO instance
	from the input and output file descriptors associated with the
	first and last processes as described by its &..system.library.Pipeline.

	Additionally, a mapping of standard errors will be produced.
	Returns a tuple, `(input, output, stderrs)`.

	Where stderrs is a sequence of file descriptors of the standard error of each process
	participating in the pipeline.
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
	Initialize a &process.Representation to manage the invocation from the (operating) system.
	This is the appropriate way to invoke a &..io process from an executable module that
	wants more control over the initialization process than what is offered by
	&.libcommand.

	#!/pl/python
		libio.execute(unit_name = (unit_initialization,))

	Creates a &Unit instance that is passed to the initialization function where
	its hierarchy is then populated with &Sector instances.
	"""

	if identity:
		ident, = identity
	else:
		ident = 'root'

	sys_inv = libsys.Invocation.system() # Information about the system's invocation.

	spr = system.Process.spawn(sys_inv, Unit, units, identity=ident)
	# import root function
	libsys.control(spr.boot, ())

_parallel_lock = libsys.create_lock()
@contextlib.contextmanager
def parallel(*tasks, identity='parallel'):
	"""
	Allocate a logical process assigned to the stack for parallel operation.
	Primarily used by blocking programs looking to leverage &.io functionality.

	A context manager that waits for completion in order to exit.

	! WARNING:
		Tentative interface: This will be replaced with a safer implementation.
		Concurrency is not properly supported and the shutdown process needs to be
		handled gracefully.
	"""
	global _parallel_lock

	_parallel_lock.acquire()
	unit = None
	try:
		join = libsys.create_lock()
		join.acquire()

		inv = libsys.Invocation(lambda x: join.release())
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
