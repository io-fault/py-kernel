"""
Core classes, exceptions, and data.

Resources use a series of stages in order to perform initialization.
"""

import os
import sys
import array
import weakref
import collections
import functools
import operator
import queue
import builtins
import types
import inspect
import itertools
import traceback
import collections.abc
import types

from ..fork import libhazmat
from ..routes import library as libroutes
from ..internet import library as libnet
from ..chronometry import library as libtime
from ..computation import library as libcomp

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
		if Class.structure in covered:
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

def format(identity, resource, tabs="\t".__mul__):
	"""
	Format the &Resource tree in eclectic text.
	"""
	import pprint

	for event in sequence(identity, resource, None, set()):
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
			modname = rc.__module__.rsplit('.', 1)[-1]
			rc_id = modname + '.' + rc.__qualname__

			actuated = "->" if resource.actuated else "-"
			if getattr(resource, 'terminating', None):
				terminated = "." if resource.terminating else ""
			else:
				terminated = "|" if resource.terminated else ""
			interrupted = "!" if resource.interrupted else ""

			yield '%s/%s [%s] %s%s%s' %(
				tabs(depth), identity, rc_id,
				actuated, terminated, interrupted
			)

def controllers(resource):
	"Return the stack of controllers of the given &Resource. Excludes initial resource."

	stack = []
	obj = resource.controller

	while obj is not None:
		add(obj)
		obj = obj.controller

	return stack

class Local(tuple):
	"A reference to a unix domain file system socket."

	__slots__ = ()

	@property
	def protocol(self):
		return 'local'

	@property
	def interface(self):
		"Directory containing the file system socket."

		return self[0]
	address = interface

	@property
	def port(self):
		"File system socket filename."

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
	A reference to a coprocess interface.

	Used by distributed services in order to refer to custom listening interfaces.

	XXX: Unused.
	# ~/.faultd/service/if/2:custom; actual socket or should it use a multiplexing connection?
	"""

	__slots__ = ()

	@property
	def protocol(self):
		return 'coprocess'

	@property
	def interface(self):
		"Relative Process Identifier"

		return self[0]

	@property
	def port(self):
		"Specific listening port; string."

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
		"The absolute unit name; &None if subjective reference."

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

	[ Properties ]

	/dependencies
		The original set of processors.
	/pending
		The current state of pending exits that must
		occur prior to the join-operation's completion.
	/callback
		The callable that is performed after the &pending
		set has been emptied.
	"""

	__slots__ = ('dependencies', 'pending', 'callback')

	def __init__(self, processors):
		"""
		Initialize the join with the given &processor set.
		"""
		self.dependencies = processors
		self.pending = set(processors)
		self.callback = None

	def connect(self):
		"""
		Connect the &Processor.atexit calls of the configured
		&dependencies to the &Join instance.
		"""
		for x in self.dependencies:
			x.atexit(self.exited)

		return self

	def __iter__(self, iter=iter):
		"""
		Return an iterator to the configured dependencies.
		"""
		return iter(self.dependencies)

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
			# XXX: calculate exceptions?

			cb = self.callback
			self.callback = None
			cb(self)

	def atexit(self, callback):
		"""
		Assign the callback of the &Join.
		If the &pending set is empty, the callback will be immediately executed,
		otherwise, overwrite the currently configured callback.
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
	Base class for Networking Layer Contexts
	"""

class Transaction(object):
	"""
	Resource allocation transaction.

	Used to manage undo operations for exception management and consolidate allocation interfaces.

	Transactions provide access to system (kernel) resources.
	Opening files, connecting to hosts, executing binaries.
	"""

	def __init__(self, sector):
		self.sector = sector
		self.context = sector.context
		self.unit = self.context.association()
		self.process = self.context.process

		assert self.unit is not None

		self.traffic = None
		self.traffic_cm = self.context.process.io(self.unit)

	def __enter__(self):
		self.traffic_cm = self.context.process.io(self.unit)
		self.traffic = self.traffic_cm.__enter__()

		return self

	def __exit__(self, exc, val, tb):
		try:
			# force the traffic loop to fall through as
			# there is a high probability that changes were
			# made that requires the junction loop's attention
			self.traffic_cm.__exit__(exc, val, tb)

			if exc:
				# rollback
				pass
		finally:
			self.process = None
			self.unit = None
			self.context = None

	def acquire_socket(self, fd):
		"""
		Allocate Transformer resources associated with the given file descriptors.
		"""

		locator = ('octets', 'acquire', 'socket')
		r, w = self.traffic(locator, fd)

		rd = Detour()
		wd = Detour()
		rd.requisite(r)
		wd.requisite(w)

		return meter_input(rd), meter_output(wd)

	def connect(self, protocol, address, port, transports = ()):
		"""
		Allocate Transformer resources associated with connections to the endpoint
		by the parameters: &protocol, &address, &port.

		Connect does not forward bind parameters.
		"""

		locator = ('octets', protocol)
		r, w = self.traffic(locator, (str(address), port))

		rd = Detour()
		wd = Detour()
		rd.requisite(r)
		wd.requisite(w)

		return meter_input(rd, transports=transports), meter_output(wd, transports=transports)

	def acquire(self, dir, *fds):
		"""
		Allocate Transformer resources associated with the given file descriptors.
		"""

		traffic = self.traffic
		locator = ('octets', 'acquire', dir)

		xf = [Detour() for x in range(len(fds))]

		for x, tr in zip(fds, xf):
			t = traffic(locator, x) # fault.traffic
			tr.requisite(t)

			yield tr

	def bind(self, binds, *transformers):
		"""
		Allocate Transformer resources associated with the given addresses.

		Usually, using &Ports is preferable.
		"""

		traffic = self.traffic
		meter = meter_input
		alloc = Allocator.allocate_integer_array

		for x in binds:
			# only one for sockets; stream of file descriptors

			locator = ('sockets', x.protocol)
			t = traffic(locator, (str(x.address), x.port))
			d = Detour()
			d.requisite(t)

			flow = Flow()
			flow.subresource(self.sector)
			flow.requisite(*(meter(d, alloc) + transformers))

			yield flow

	def listen(self, receiver, fds):
		"""
		Allocates flows for the given file descriptors &fds and connect them to the &receiver.

		Like &bind, but works with already allocated sockets.
		"""

		traffic = self.traffic
		meter = meter_input
		alloc = Allocator.allocate_integer_array
		sector = self.sector

		for x in fds:
			locator = ('sockets', 'acquire')
			t = traffic(locator, x)
			d = Detour()
			d.requisite(t)

			flow = Flow()
			flow.requisite(*meter(d, allocate=alloc))
			flow.subresource(sector)
			sector.dispatch(flow)
			flow.connect(receiver)

			yield flow

	def append(self, path):
		"""
		Allocate a Detour appending data to the given file.
		"""

		t = self.traffic(('octets', 'file', 'append'), path)
		d = Detour()
		d.requisite(t)

		return meter_output(d)

	def flow(self, *sequences, chain=itertools.chain):
		"""
		Create a flow and designate the sequences of Transformers
		as its requisites (pipeline).

		Each arguments must be sequences of transformers.
		"""
		global Flow

		f = Flow()
		f.subresource(self.sector)
		f.requisite(*chain(*sequences))

		return f

	def flows(self, count=2, range=range):
		"Construct flows identifying the transaction's processor as its controller."
		global Flow

		u = self.unit
		for x in range(count):
			f = Flow()
			f.subresource(self.sector)
			yield f

	def system(self, invocation):
		"""
		Execute the &..fork.library.KInvocation inheriting standard input, output, and error.

		This is used almost exclusively by shell-type processes.
		"""

		sp = Subprocess()
		pid = invocation()
		sp.requisite((pid,))

		return sp

	def pipeline(self, kpipeline, input=None, output=None):
		"""
		Execute a &..fork.library.KPipeline object building an IO instance
		from the input and output file descriptors associated with the
		first and last processes as described by its &fork.library.Pipeline.

		Additionally, a mapping of standard errors will be produced.
		Returns a tuple, `(input, output, stderrs)`.

		Where stderrs is a sequence of file descriptors of the standard error of each process
		participating in the pipeline.
		"""

		pl = kpipeline()

		try:
			input = self.acquire('input', pl.input)
			output = self.acquire('output', pl.output)

			stderr = list(self.acquire('input', pl.standard_errors))

			sp = Subprocess()
			sp.requisite(pl.process_identifiers)
		except:
			pl.void()
			raise

		return sp, input, output, stderr

	def pipeline_from_ports(self, kpipeline, input, output, *errors):
		"""
		Not Implemented.

		Construct a pipeline from the given file descriptors (kernel ports), &input, &output, and
		&errors. This interface is used to construct a pipeline whose I/O needs to be directed
		to particular files.

		&kpipeline expects that invoking application to manage the input and output from the pipeline,
		but that is not desirable when directing the output to the filesystem.
		"""

		# only use file descriptors to allow user to select the FD's positioning
		pass

	def daemon(self, invocation, close=os.close):
		"""
		Execute the &..fork.library.KInvocation instance with stdin and stdout closed.
		Standard error's file descriptor is returned as a &Detour along with
		the &Subprocess: (&Subprocess, &Detour).
		"""

		global Subprocess

		stdout = stdin = stderr = ()

		try:
			try:
				# use dev/null?
				stderr = os.pipe()
				stdout = os.pipe()
				stdin = os.pipe()

				pid = invocation(fdmap=[(stderr[1], 2), (stdout[1], 1), (stdin[0], 0)])
			finally:
				# clean up file descriptors

				for x in stderr[1:]:
					close(x)
				for x in stdout:
					close(x)
				for x in stdin:
					close(x)

			sp = Subprocess()
			sp.requisite((pid,))
		except:
			close(stderr[0])
			raise

		stderr_read = list(self.acquire('input', stderr[0]))[0]

		return (sp, stderr_read)

	def daemon_stderr(self, stderr, invocation, close=os.close):
		"""
		Execute the &..fork.library.KInvocation instance with stdin and stdout closed.
		The &stderr parameter will be passed in as the standard error file descriptor,
		and then *closed* before returning.

		Returns a &Subprocess instance containing a single Process-Id.

		Used to launch a daemon with a specific standard error.
		"""
		global Subprocess

		stdout = stdin = stderr = ()

		try:
			# use dev/null?
			stdout = os.pipe()
			stdin = os.pipe()

			pid = invocation(fdmap=[(stderr, 2), (stdout[1], 1), (stdin[0], 0)])
		finally:
			# clean up file descriptors
			close(stderr)

			for x in stdout:
				close(x)
			for x in stdin:
				close(x)

		sp = Subprocess()
		sp.requisite((pid,))

		return sp

	def stream_file(self, path, range, *downstream, Segments=libhazmat.Segments):
		"""
		Construct a new Flow with an initial Iterate Transformer
		flowing shared memory segments from the memory mapped file.

		Returns a pair, the new Flow and a callable that causes the Flow to begin
		transferring memory segments.

		[ Parameters ]

		/path
			Local filesystem path.

		/range
			A triple, (start, stop, size), or &None if the entire file should be used.
			Where size is the size of the memory slices to emit.

		/downstream
			The set of &Transformer instances that follow the &Iterate instance.
		"""
		global Iterate, Flow

		segs = Segments.open(path, range)
		sector = self.sector

		f = Flow()
		i = Iterate()
		f.requisite(i, *downstream)
		sector.dispatch(f)

		return f, functools.partial(f.process, s)

class Resource(object):
	"""
	Base class for the Resource and Processor hierarchy making up a fault.io process.
	"""

	context = None
	controller_reference = lambda x: None

	controller = property(
		fget = dereference_controller,
		fset = set_controller_reference,
		doc = "controller property for process resources"
	)

	@property
	def sector(self, isinstance=isinstance):
		"Identify the &Sector holding the &Resource by scanning the &controller stack."

		global Sector

		c = self.controller
		while c and not isinstance(c, Sector):
			c = c.controller

		return c

	def __init__(self):
		""
		pass

	def __repr__(self):
		c = self.__class__
		mn = c.__module__.rsplit('.', 1)[-1]
		qn = c.__qualname__

		return '<%s.%s at %s>' %(
			mn, qn, hex(id(self))
		)

	def subresource(self, ascent, Ref=weakref.ref):
		"""
		Assign &ascent as the controller of &self and inherit its &Context.
		"""

		self.controller_reference = Ref(ascent)
		self.context = ascent.context

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

class Extension(Resource):
	"""
	A resource that is intended solely for delegation from other resources.

	Extension resources must subresources from non-Unit resources and should only
	appear within Sectors.
	"""

class Device(Resource):
	"""
	A resource that is loaded by &Unit instances into (io.resource)`/dev`

	Devices often have special purposes that regular &Resource instances do not
	normally fulfill. The name is a metaphor for operating system kernel devices
	as they are often associated with kernel features.
	"""

	@classmethod
	def load(Class, unit):
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

	# XXX: Use bitmap and properties for general states.
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
		"""

		return self.actuated and not (self.terminated or self.interrupted)

	def controlled(self, subprocessor):
		"Whether or not the given &Processor is directly controlled by &self"

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
		"Note as actuated; abstract Processors have no actuation."

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

		self.terminating = True
		self.terminator = by

	def interrupt(self, by=None):
		"""
		Note the processor as being interrupted.

		Subclasses must perform any related resource releases after
		calling the superclass's implementation.

		Only &Sector interrupts cause exits.
		"""

		self.interruptor = by
		self.interrupted = True

	def fault(self, exception, association=None):
		"""
		Note the given exception as an error on the &Processor.

		Exceptions identified as errors cause the &Processor to exit.
		"""

		if self.exceptions is None:
			self.exceptions = set()

		self.exceptions.add((association, exception))
		self.context.faulted(self)

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

	def __await__(self):
		"""
		Coroutine interface support. Await the exit of the processor.
		Awaiting the exit of a processor will never raise exceptions with
		exception to internal (Python) errors. This is one of the notable
		contrasts between Python's builtin Futures and fault.io Processors.
		"""

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

	def exit_event_emit(self, processor, partial=functools.partial):
		"Called when an exit occurs to emit exit events to any connected callbacks."

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

class Call(Processor):
	"""
	A single call represented as a Processor.

	The callable is executed on actuation and signals its exit
	after completion.

	Used as an abstraction to explicit enqueues, and trigger faults in Sectors.
	"""

	def __init__(self, call):
		super().__init__()
		self.call = call

	def actuate(self):
		super().actuate()

		try:
			self.product = self.call(self)
			self.terminated = True
		except BaseException as exc:
			self.product = None
			self.fault(exc)
		finally:
			self.controller.exited(self)

		return self

	def structure(self):
		return ([('call', self.call)], ())

class Unit(Processor):
	"""
	An asynchronous logical process. Unit instances are the root level objects
	associated with the &Process instance. There can be a set of &Unit instances
	per process, but usually only one exists.

	Units differ from most &.core.Processor classes as it provides some additional
	interfaces for managing exit codes and assigned standard I/O interfaces
	provided as part of the system process.

	Units are constructed from a set of roots that build out the &Sector instances
	within the runtime tree which looks similar to an in memory filesystem.
	"""

	@property
	def ports(self):
		"(io.location)`/dev/ports` accessor"

		return self.index[('dev','ports')]

	@property
	def scheduler(self):
		"(io.location)`/dev/scheduler` accessor"

		return self.index[('dev','scheduler')]

	def load_ports_device(self):
		"Load the &Ports 'device'. Usually used by daemon processes."

		ports = Ports()
		self.place(ports, 'dev', 'ports')
		ports.subresource(self)

	def device(self, entry):
		"Return the device resource placed at the given &entry."

		return self.index.get(('dev', entry))

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
			path = self.reverse_index.get(faultor)

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
		index = [('/'.join(k), v) for k, v in self.index.items() if v is not None]
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

		self.terminated = None
		self.identity = self.identifier = None
		self.libraries = Libraries(self)

		# total index; tuple -> sector
		self.index = dict()
		self.reverse_index = dict()

		self.roots = [] # initialization functions

		# tree containing sectors; navigation access
		self.hierarchy = dict(
			bin = dict(), # Sectors that determine Unit's continuation
			lib = dict(), # Library Sectors; terminated when bin/ is empty.
			data = dict(),
			dev = dict(),
			faults = dict(),
		)

		# Purely for containment
		self.index[('bin',)] = None
		self.index[('lib',)] = None
		self.index[('data',)] = None
		self.index[('dev',)] = None
		self.index[('faults',)] = None

	def requisite(self,
			identity:collections.abc.Hashable,
			roots, process = None, context = None, Context = None
		):
		"""
		Ran to finish &Unit initialization; extends the sequences of roots used
		to initialize the root sectors.
		"""

		self.identity = identity

		# make sure we have a context
		if context is None:
			context = Context(process)
			context.associate(self)
			self.context = context

		self.roots.extend(roots)

	def exited(self, processor:Processor):
		"Processor exit handler."

		addr = self.reverse_index.pop(processor)
		del self.index[addr]

		if processor.exceptions:
			# Redundant with Sector.exited
			# But special for Unit exits as we have the address
			self.faulted(processor, path = addr)

		if addr[0] == 'bin' and not self.index[('bin',)]:
			ctl = self.index.get(('control',))
			if ctl is not None:
				ctl.exit(self)
			else:
				# Unit has no more executables.
				self.terminate()

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
		scheduler.requisite(scheduler=self.context)
		self.place(scheduler, 'dev', 'scheduler')
		scheduler.actuate()

		self.place(self.context.process, 'dev', 'process')

		for sector_init in self.roots:
			sector_init(self)

	def link(self, **paths):
		"""
		Link a set of libraries into the &Unit.
		"""

		for libname, route in paths.items():
			lib = Library(route)
			self.place(lib, 'lib', libname)
			lib.subresource(self)
			lib.actuate()

	def terminate(self):
		global __process_index__

		if self.terminated is not True:
			if self.context.process.primary() is self:
				if self.hierarchy['faults']:
					self.context.process.report()
				self.context.process.terminate(getattr(self, 'result', 0))
				self.terminated = True
			else:
				self.terminated = True

	def place(self, obj : collections.abc.Hashable, *destination):
		"""
		Place the given object in the program at the specified location.
		"""

		self.index[destination] = obj

		try:
			# build out path
			p = self.hierarchy
			for x in destination:
				if x in p:
					p = p[x]
				else:
					p[x] = dict()

			if destination[0] != 'faults':
				# Don't place into reverse index.
				self.reverse_index[obj] = destination
		except:
			del self.index[destination]
			raise

	def delete(self, *address):
		"""
		Remove a &Sector from the index and tree.
		"""

		obj = self.index[address]
		del self.reverse_index[obj]
		del self.index[address]

	def listdir(self, *address, list=list):
		"""
		List the contents of an address.
		This only includes subdirectories.
		"""

		p = self.hierarchy
		for x in address:
			if x in p:
				p = p[x]
			else:
				break
		else:
			return list(p.keys())

		# no directory
		return None

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

	/(&Schduler)scheduler
		The Sector local schduler instance for managing recurrences and alarms
		configured by subresources. The exit of the Sector causes scheduled
		events to be dismissed.

	/exits
		Set of Processors that are currently exiting.
		&None if nothing is currently exiting.
	"""

	projection = None
	exits = None
	product = None
	scheduler = None
	processors = None

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

	def __init__(self, Processors=functools.partial(collections.defaultdict,set)):
		super().__init__()

		# initialized here in order to allow requisite to function
		self.processors = Processors()

	def actuate(self):
		"""
		Actuate the Sector by actuating its processors.
		There is no guarantee to the order in which they are actuated.

		Exceptions that occur during actuation fault the Sector causing
		the controlling sector to exit.
		"""

		try:
			for Class, sset in self.processors.items():
				for proc in sset:
					proc.actuate()
		except BaseException as exc:
			self.fault(exc)

		return super().actuate()

	def requisite(self, *procs):
		"""
		Add a set Processors to the Sector to be dispatched on Sector actuation.
		"""

		sprocs = self.processors
		for proc in procs:
			sprocs[proc.__class__].add(proc)
			proc.subresource(self)

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
		super().terminate(by)

		if self.processors:
			# Rely on self.reap() to finish termination.
			for Class, sset in self.processors.items():
				for x in sset:
					x.terminate()
		else:
			# Nothing to wait for.
			self.terminating = False
			self.terminated = True
			self.controller.exited(self)

	def interrupt(self, by=None):
		"""
		Interrupt the Sector by interrupting all of the subprocessors.
		The order of interruption is random, and *should* be insignificant.
		"""

		if self.interrupted:
			return

		super().interrupt(by)

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
		self.processors[processor.__class__].add(processor)
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

	def reap(self, set=set):
		"Empty the exit set and check for sector completion."

		exits = self.exits
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

			controller = self.controller
			if controller is not None:
				controller.exited(self)

	def allocate(self):
		"""
		Create a Resource Allocation Transaction for creating sockets and spawning processes.
		"""

		global Transaction
		return Transaction(self)
	xact = allocate

class Controller(Sector):
	"""
	Sector designed to manage and control a specific set of Processors.

	&Controller sectors are first different from regular Sectors in that
	they do not exit when empty as they provide a service.
	"""

	def reaped(self):
		if self.terminating:
			super().reaped()

class Control(Sector):
	"""
	A control sector that provides an exit handler for the &Unit.
	Control instances are used by daemon processes to manage the control interfaces
	to the process.

	By default, the Control &Sector exits as if there was no control instance.
	"""

	def exit(self, unit):
		"""
		Called when /control is present and /bin is emptied.
		If not overridden by a subclass, the process will exit.
		"""

		unit.terminate()

	def halt(self, source):
		"""
		Handle an administrative or automated request to halt the daemon.
		Shuts down acquire slots from &Interfaces in order to cease gaining work.
		The &Interface instances assigned to the root Sector will be removed after
		being flushed. Subsequently, the root Sector will exit when its work is complete.
		"""

		unit = self.context.association()

	# XXX: stop/continue?
	def pause(self):
		"""
		Handle an administrative request to pause (SIGSTOP) the daemon.
		"""

		pass

	def resumed(self):
		"""
		Called automatically when the daemon has been resumed (SIGCONT).
		"""

		pass

class SectorModule(Sector):
	"""
	A Sector that is initialized by a specified module.

	&SectorModule instances are intended to be root &Sector instances within a &Unit.
	It is expected that the execution context is associated with the unit in which
	it exists: `self.context.association() == self.controller`.
	"""

	class Access(object):
		__slots__ = ('_interfaces_',)

		def __init__(self, lib, exports, partial=functools.partial):
			self._interfaces_ = {k:partial(v,lib) for k,v in exports.items()}

		def __getattr__(self, attr):
			try:
				return self._interfaces_[attr]
			except KeyError:
				raise AttributeError(attr)

	class API(object):
		"""
		API Parameter builder for API class exports.

		Supports the @api decorator.
		"""

		def __init__(self, sector):
			self.__sector = sector
			self.__params = {}
			self.__class = None

		def version(self, vspec):
			self.__params['version'] = vspec
			return self

		def __call__(self, commit):
			# commit the API class to its configured slot
			self.__class = commit

	# Requisites
	exports = None
	autostart = None
	module = None
	route = None

	def requisite(self, route):
		if route.spec() is None:
			raise ImportError(route.fullname)

		self.route = route

	def prepare(self, mod):
		"""
		Prepare the module's dictionary.

		Provisions:

		/export
			&add_export
		/boot
			&add_autostart
		/lib
			Unit &Libraries instance.
		/io
			&io.library module.
		"""

		mod.export = self.add_export
		mod.api = self.API(self)
		mod.boot = self.add_autostart
		mod.lib = self.context.association().libraries
		mod.sector = weakref.ref(self)

		from . import library
		mod.io = library

	@classmethod
	def from_fullname(Class, path, ir_from_fullname=libroutes.Import.from_fullname):
		rob = Class()
		rob.requisite(ir_from_fullname(path))
		return rob

	def add_export(self, callable, name=None):
		"Register the callable as an API entry point."

		self.exports[name or callable.__name__] = callable
		return callable

	def add_autostart(self, callable):
		"Identify a module function as a Processor to be ran on actuation."

		self.autostart.append(callable)
		return callable

	def api(self):
		"Return an &Access instance to the module's exports."

		return self.Access(self, self.exports)

	def actuate(self, ModuleType=types.ModuleType):
		super().actuate()

		self.exports = {}
		self.autostart = []

		mod = ModuleType(self.route.fullname)

		self.module = mod
		self.prepare(mod)
		self.route.spec().loader.exec_module(mod)

		# XXX: interrupts sectors
		for autostart in self.autostart:
			autostart(self)

		# Remove reference cycles.
		del self.module.export
		del self.module.boot

		return self

class Executable(SectorModule):
	"""
	A root Sector that is sourced by a module.

	&Executable instances are normally loaded into "/bin"
	"""

class Library(SectorModule):
	"""
	A root &Sector that is specially managed by &Unit instances inside
	the "/lib" directory in the runtime tree.

	Libraries expose API for use by other libraries and executing &Sector instances.
	They have the advantage of maintaining caches that can be used by all
	root &Sector instances being managed by a &Unit.

	Libraries are implemented with Python modules that define the exposed API.
	"""

	def actuate(self):
		"""
		Call the `lib_init` function in the module.
		"""

		super().actuate()

		if 'lib_init' in self.module.__dict__:
			return self.module.lib_init(self)

		return self

class Subprocess(Processor):
	"""
	A Processor that represents a *set* of Unix subprocesses.
	Primarily exists to map process exit events to processor exits and
	management of subprocessor metadata such as the Process-Id of the child.
	"""

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
		"The exit event of the only Process-Id. &None or the pair (pid, exitcode)."

		for i in self.process_exit_events:
			return i, self.process_exit_events.get(i)

		return None

	def requisite(self, pids):
		self.process_exit_events = {}
		self.active_processes = set(pids)

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

	def signal(self, signo):
		"""
		Send the given signal number (os.kill) to the active processes
		being managed by the instance.
		"""
		global os

		send_signal = os.kill

		for pid in self.active_processes:
			send_signal(pid, signo)

	def actuate(self):
		"""
		Initialize the system event callbacks for receiving process exit events.
		"""

		proc = self.context.process

		for pid in self.active_processes:
			proc.system_event_connect(('process', pid), self, self.sp_exit)
			proc.kernel.track(pid)

		return super().actuate()

	def terminate(self, by=None, signal=15):
		if not self.terminating:
			super().terminate(by=by)
			self.signal(signal)

	def interrupt(self, by=None):
		# System Events remain connected; still want sp_exit.
		super().interrupt(by)
		self.signal(9)

class Commands(Processor):
	"""
	A conditionally executed series of subprocesses.
	Similar to shell commands with control operators.

	#!/pl/python
		cmds = Commands()
		cmds.requisite(index)
		cmds.follow('cmd_index_name')
		cmds.success('cmd2_index_name')
		cmds.failed('failure_handler_name')
		cmds.follow('indendent')

	Successes are strongly grouped. (&failed applies to series of successes)
	"""

	def requisite(self, index=None):
		"""
		Define the command index that makes up the sequence.
		"""

		self.index = index

	def success(self):
		"""
		Execute the Invocation if the prior returned zero.
		"""

		pass

	def failed(self):
		"""
		Execute the Invocation if the prior returned a non-zero result.
		"""

		pass

	def follow(self):
		"""
		Unconditionally execute the invocation when the point is reached.
		"""

		pass

	def actuate(self):
		super().actuate()

class Recurrence(object):
	"""
	Timer maintenance for recurring tasks.

	Usually used for short term recurrences such as animations and human status updates.
	"""

	__slots__ = ('target', 'scheduler')

	def __init__(self, scheduler, target):
		self.scheduler = weakref.proxy(scheduler)
		self.target = target

	def occur(self):
		"Invoke a recurrence and use its return to schedule its next iteration."

		next_delay = self.target()
		if next_delay is not None:
			self.scheduler.defer(next_delay, self.occur)

class Scheduler(Processor):
	"""
	Delayed execution of arbitrary callables.
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

	def requisite(self, scheduler=None, persistent=True):
		self.persistent = persistent # Processor remains when no tasks deferred.

		if scheduler is not None:
			self.x_ops = (
				(scheduler.defer),
				(scheduler.cancel),
			)

	def actuate(self):
		self.state = libtime.Scheduler()

		# XXX: resolve the scheduler to use; Context or controlling-Sector
		# XXX: scheduler resolution needs tests
		if self.x_ops is None:
			controller = self.controller
			while controller is not None:
				if hasattr(controller, 'scheduler'):
					sched = controller.scheduler
					if sched is not None:
						break
				controller = controller.controller
			else:
				# Use [unit]/dev/scheduler
				sched = self.context.association().scheduler

			self.requisite(scheduler = sched)

		return super().actuate()

	@staticmethod
	def execute_weak_method(weakmethod):
		return weakmethod()()

	def update(self):
		"Update the scheduled transition callback."

		# Use a weakref here as we do not want
		# to keep an instance from being garbage collected.

		nr = weakref.WeakMethod(self.transition)
		if self.scheduled_reference is not None:
			self.x_ops[1](self.scheduled_reference)

		sr = self.scheduled_reference = functools.partial(self.execute_weak_method, nr)
		self.x_ops[0](self.state.period(), sr)

	def schedule(self, pit, *tasks, now=libtime.now):
		"""
		Schedule the &tasks to be executed at the specified Point In Time, &pit.
		"""

		measure = now().measure(pit)
		return self.defer(measure, *tasks)

	def defer(self, measure, *tasks):
		"Defer the execution of the given &tasks by the given &measure."

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
		"Cancel the execution of the task."

		self.state.cancel(task)

	def recurrence(self, callback):
		"Begin a recurring task."

		r = Recurrence(self, callback)
		r.occur()
		return r

	def transition(self):
		"""
		Execute the next task given that the period has elapsed.
		If the period has not elapsed, reschedule &transition in order to achieve
		finer granularity.
		"""

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
					# falls back to class attribute
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
				raise ValueError("scheduler requires a chronometry.library.Unit")

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

	def requisite(self, callable):
		self.callable = callable

	def actuate(self):
		"""
		Execute the dedicated thread for the transformer.
		"""

		super().actuate()
		self.context.execute(self, self.callable, self)
		return self

	def process(self):
		"""
		No-op as the thread exists to emit side-effects.
		"""
		pass

class Coroutine(Processor):
	"""
	Processor for generator based coroutine.

	Manages the generator state in order to signal the containing &Sector of its
	exit. Generator coroutines are the common mechanism for serializing the dispatch of
	work to relevant &Sector instances.
	"""

	@classmethod
	def from_callable(Class, generator_function):
		"""
		Construct a generator from a function taking the &Sector as a parameter.
		"""

		r = Class()
		g = generator_function(r)
		r.state = g

		return r

	@classmethod
	def from_generator(Class, generator):
		"""
		Construct a coroutine from an already running generator.
		"""

		r = Class()
		r.state = g
		return r

	def __init__(self):
		super().__init__()
		self.state = None

	@types.coroutine
	def container(self, coroutine):
		# Adapt the coroutine's exit to Processor exit.
		try:
			self.product, = (yield from coroutine)
		except Exception as exc:
			self.product = None
			self.faulted(exc)
		finally:
			self.sector.exited(self)

	def continued(self, processor):
		self.process(processor.product)

	def process(self, event, source = None, partial=functools.partial, StopIteration=StopIteration):
		"""
		Send the event to the running generator causing a continuation.
		"""

		try:
			# cb allows us to chain continuations
			processor = self.state.send(event)
			if processor is not None:
				processor.atexit(self.continued)
			else:
				self.context.enqueue(partial(self.process, None))
		except StopIteration:
			self.sector.exited(self)
		else:
			# coroutine protocol violation
			pass

	def actuate(self):
		"""
		Start the generator.
		"""

		self.process(None)
		return self

# Interface is the handle on the set of connection for clients.
# The API being supported by the Interface defined by a subclass
# The port bindings are reusable?
# Accept handled similarly?

class Interface(Sector):
	"""
	An Interface Sector used to manage a set of Connection instances.

	Usually, Interfaces are the mechanism used to automate the aquisition of sockets
	in the /dev/ports device;
	a link back is provided to allow natural halting of a daemon process. Ports being
	the primary way that a daemon acquires new work, a &Control instance can begin
	the administrative termination process by closing the listening sockets acquired
	by the &Interface instances.
	"""

	bindings = None
	spawn = None
	slot = None

	def structure(self):
		p = [
			('spawn', self.spawn),
			('slot', self.slot),
			('bindings', self.bindings),
		]
		return (p, ())

	def requisite(self, slot, spawn, inverse=False):
		"""
		/slot
			The slot to acquire from the &Ports instance assigned to "/dev/ports".

		/spawn
			The function used to initialize the subsector created to handle a connection.
		"""

		self.slot = slot
		self.spawn = spawn
		self.inverse = inverse # XXX: inverse being client connections; unused

	def actuate(self):
		global Flow, Sector

		super().actuate()

		self.bindings = set()

		self.funnel = Funnel()
		Funnel.requisite(self.funnel) # defaults
		Flow.requisite(self.funnel, Spawn(self.spawn))
		self.dispatch(self.funnel)

		if self.inverse:
			pass
		else:
			ports = self.context.association().ports
			fds = ports.acquire(self.slot)

			with self.xact() as xact:
				add = self.bindings.add

				for x in xact.listen(self.funnel, fds.values()):
					add(x)
					self.dispatch(x)
					x.process(None) # Start allocating.

		return self

class Protocol(Processor):
	"""
	A &Processor that manages protocol state. Usually, protocols are generalized
	into &Flow divisions coupled with &Layer context events signalling the initiation
	and completion of protocol transactions.
	"""

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
		self.emit(event)

	def process(self, event):
		self.emit(event)

	def actuate(self):
		pass

	def emit(self, event):
		raise RuntimeError("emit property was not set to the following transformer")

	def drain(self):
		pass

	def terminate(self):
		pass

	def interrupt(self):
		pass

class Autonomous(Transformer):
	"""
	Transformer that doesn't maintain context or reference a controller.

	Non-functional at the moment; transformers need to be able to define how
	the adjacents connect to it.

	XXX: not functional
	"""

	@property
	def controller(self):
		return None

	@controller.setter
	def controller(self, val):
		pass

	@property
	def context(self):
		return None

	@context.setter
	def context(self):
		pass

	@property
	def process(self):
		pass

class Reflection(Transformer):
	"""
	Transformer that performs no modifications to the processed events.

	Reflections are Transformers that usually create some side effect based
	on the processed events.
	"""

class Transports(Transformer):
	"""
	Transformer whose purpose is to encode and decode events in order
	to facilitate the desired conceptual Transport.

	Transports represents a stack of protocol layers and manages their
	initialization and termination so that the outermost layer is
	terminated before the inner layers, and vice versa for initialization.

	Transports are primarily used to manage TLS.
	"""

	def __repr__(self, format="<{path} [{stack}]>"):
		path = self.__class__.__module__.rsplit('.', 1)[-1]
		path += '.' + self.__class__.__qualname__
		return format.format(path=path, stack=repr(self.stack))

	@property
	def opposite(self):
		"The transformer of the opposite direction for the Transports pair."
		return self.opposite_transformer()

	def requisite(self, opposite):
		"Opposite transformer is needed to propagate opposing reactions."

		self.opposite_transformer = weakref.ref(opposite)

	operations = ()
	def configure(self, polarity, stack, *operations):
		"""
		Assign the sequence of layer operations.

		The layer operations are pairs consisting of the operations for the
		read transports and write transports. The positioning is subjective,
		so if the input Transformer is being configured, the first item in
		the pair should be the input operations.
		"""

		self.polarity = polarity
		stack = self.stack = list(stack)
		self.operations = [x[0] for x in operations]

		opp = self.opposite
		opp.polarity = -polarity
		opp.stack = stack
		opp.operations = [x[1] for x in reversed(operations)]

	callbacks = None
	def atshutdown(self, callback):
		if self.callbacks is None:
			self.callbacks = set()

		self.callbacks.add(callback)

	def drained(self):
		callbacks = self.callbacks
		if callbacks is not None:
			del self.callbacks
			for drain_complete_cb in callbacks:
				drain_complete_cb()

	def drain(self):
		"""
		Drain the transport layer.

		Buffers are left as empty as possible, so flow termination is the only
		condition that leaves a requirement for drain completion.

		Drain is how &Transport manages properly sequenced termination
		for the security layer; TLS must be terminated prior to their
		corresponding transports (Detours).
		"""

		if self.stack:
			flow = self.controller
			if flow.terminating:
				if flow.permanent:
					# flow is permanently obstructed and transfers
					# are irrelevant at one level or another
					# so try to process whatever is available, finish
					# the drain operation so termination can finish.
					self.process(())
					opp = self.opposite
					if opp.callbacks:
						# Process anything available, and identify it as drained.
						opp.process(())
						opp.drained()
					else:
						opp.controller.terminate(by=self)
					return None
				else:
					# signal transport that termination needs to occur
					self.stack[0].terminate(self.polarity)
					self.process(())
					# drain is complete when shutdown is received
					return self.atshutdown

		# Not terminating, no flushes necessary.
		# XXX: zero transfer?
		return None

	def process(self, events, termination=False):
		opposite_has_work = False

		if not self.operations:
			self.emit(events)
			return

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
			self.emit(events)

		# Termination must be checked everytime.
		if self.stack[0].terminated and not termination:
			# *fully* terminated. pop item after allowing the opposite to complete

			# This needs to be done as the transport needs the ability
			# to flush any remaining events in the opposite direction.
			opp = self.opposite
			# (Avoid an infinite loop using the termination keyword.)
			opp.process((), termination=True)

			del self.stack[0]
			# operations is perspective sensitive
			if self.polarity > 0:
				# recv/input
				del self.operations[-1]
				del opp.operations[0]
			else:
				# send/output
				del self.operations[0]
				del opp.operations[-1]

			if not self.stack:
				# signal drain completion if stack is empty
				opp.drained()
				self.drained()
			else:
				# Otherwise, the next stack needs to terminated,
				# if the controller is terminating.
				if opp.controller.terminating:
					opp.stack[0].terminate(-self.polarity)
				if self.controller.terminating:
					self.stack[0].terminate(self.polarity)

		elif opposite_has_work and not termination:
			# Use recursion on purpose to allow
			# the maximum stack depth to block an infinite loop.
			self.opposite.process(())

class Terminal(Transformer):
	"""
	A Transformer that never emits.

	Subclasses of &Terminal make the statement that they too do not emit any events.
	Not all &Flow instances contain &Terminal instances.
	"""

	def inject(self, event):
		"Accept the event, but do nothing as Terminals do not propogate events."
		pass

	def process(self, event):
		"Accept the event, but do nothing as Terminals do not propogate events."
		pass

class Reactor(Transformer):
	"""
	A Transformer that is sensitive to Flow obstructions.

	Reactors are distinct from Transformers in that they automatically receive obstruction
	notifications in order to relay failures to dependencies that fall outside the &Flow.

	Installation into A &Flow causes the &suspend and &resume methods to be called whenever the
	&Flow is obstructed or cleared.
	"""

	def subresource(self, obj):
		super().subresource(obj)
		obj.watch(self.suspend, self.resume) # relocate to Reactor.actuate

	def suspend(self, flow):
		"Method to be overridden for handling Flow obstructions"
		pass

	def resume(self, flow):
		"Method to be overridden for handling Flow clears"
		pass

class Parallel(Transformer):
	"""
	A dedicated thread for a Transformer. Often used for producing arbitrary injection events
	produced by blocking calls.

	Term Parallel being used as the actual function is ran in parallel to
	the &Flow in which it is participating in.

	The requisite function should have the following signature:

		def thread_function(transformer, queue, *optional):
			...

	The queue provides access to the events that were received by the Transformer,
	and the &transformer argument allows the thread to cause obstructions by
	accessing its controller.
	"""

	def __init__(self, callable, parameters):
		super().__init__()

		global queue
		self.callable = callable
		self.parameters = parameters

	def requisite(self, callable, *parameters):
		self.callable = callable
		self.parameters = parameters

	def actuate(self):
		"""
		Execute the dedicated thread for the transformer.
		"""

		self.queue = queue.Queue()
		self.put = self.queue.put
		self.context.execute(self, self.callable, *((self, self.queue) + self.parameters))
		return self

	def process(self, event):
		"""
		Send the event to the queue that the Thread is connected to.
		Injections performed by the thread will be enqueued into the main task queue.
		"""

		self.put(event)

	def terminate(self):
		self.put(None)

# XXX: Dispatcher needs to signal obstructions when the queue size reaches a configured value.
# XXX: Dispatcher does not guarantee serialization.
class Dispatcher(Transformer):
	"""
	A Processor that applies the function in a general purpose thread and enqueues the
	emission (results) to the process' task queue.
	"""

	enqueue = None
	dispatch = None

	def requisite(self, function, serialization = None):
		self.function = function
		self.serialization = serialization

	def actuate(self, partial=functools.partial):
		self.enqueue = self.context.enqueue
		self.dispatch = self.context.dispatch

		if self.serialization is None:
			self.method = partial(self.imperfect, self.function)
		else:
			self.method = partial(self.serializing, self.function)

		return self

	@classmethod
	def serialized(Class, function):
		"""
		Create a Parallel processor instance that guarantees serialization of processing
		operations.
		"""

		rob = Class()
		rob.requisite(function, libhazmat.create_knot())
		return rob

	# races with general purpose threads > 1; serialization order is not guaranteed
	def serializing(self, function, event, partial = functools.partial):
		with self.serialization:
			emission = function(event)
			# enqueue emission for next transformer
			self.enqueue(partial(self.emit, emission))

	def imperfect(self, function, event):
		emission = function(event)
		self.enqueue(functools.partial(self.emit, emission))

	def process(self, event):
		self.dispatch(self, functools.partial(self.method, event))

	retains = True
	def drained(self, callback):
		# XXX: Needs to be able to select the GPT.
		with self.serialization:
			self.enqueue(callback)

	def ddrain(self, callback):
		self.dispatch(self, functools.partial(self.drained, callback))

	def drain(self):
		return self.ddrain

class Generator(Dispatcher):
	"""
	A &Dispatcher that sends events to a generator that is iterated within a general purpose thread.
	"""

	def requisite(self, function):
		"Install a generator function to support transformations."

		self.generator = function(self)
		super().requisite(self.generator.send, serialization = libhazmat.create_knot())
		self.generator_function = function

	def subresource(self, ascent):
		super().subresource(ascent)
		next(self.generator)

	def emission(self, event, partial = functools.partial):
		"""
		A means to vent emission before yielding out of a generator.
		"""

		return self.enqueue(partial(self.emit, event))

	def serializing(self, function, event):
		"""
		Generators have to be serialized.
		"""

		# inside a general purpose thread
		with self.serialization:
			# trap exceptions while serializing.
			try:
				# generators call emission directly
				result = function(event)
			except StopIteration:
				# XXX: signal obstruction or interruption?
				pass

class Detour(Transformer):
	"""
	Transformer moving received events through a transit and back into the
	flow that the Loop is participating in.
	"""

	def __init__(self):
		self.transit = None

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

	def requisite(self, transit=None):
		self.transit = transit
		#transit.resize_exoresource(1024*128)
		self.acquire = transit.acquire
		transit.link = self

	def actuate(self):
		self.process = self.transit.acquire

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
			t.link = None
			t.terminate()
	interrupt = terminate

	def terminated(self):
		# THIS METHOD IS NOT CALLED IF TERMINATE/INTERRUPT() WAS USED.

		# Called when the termination condition is received,
		# but *after* any transfers have been injected.

		# io.traffic calls this.

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
			flow.obstruct(self, None, Inexorable)
			flow.terminate(self)

	def process(self, event):
		# This method is actually overwritten on actuate.
		# process is set to Transit.acquire.
		self.transit.acquire(event)

class Functional(Transformer):
	"A transformer that emits the result of a provided function."

	def __init__(self, function=None):
		self.function = function

	def process(self, event):
		self.emit(self.function(event))

	@classmethod
	def generator(Class, g):
		"Create a functional transformer using a generator"

		next(g)
		return Class(g.send)

# XXX: Compoistion Transformer needs tests
class Composition(Functional):
	"""
	Mutable transformer used to manage a functional composition.

	Compositions are preferable to distinct Transformers for their
	mutable capabilities. This allows protocol switches to be performed

	Used heavily in meter_input and meter_output in order to allow protocol
	substitutions.
	"""

	def structure(self):
		p = [
			(i, self.sequence[i])
			for i in range(len(self.sequence))
		]
		return (p, ())

	def actuate(self):
		if self.function is None:
			self.compose()

	def compose(self, *sequence, Compose=libcomp.compose):
		"Substitute the composition of the Transformation."

		self.sequence = sequence
		self.function = Compose(*sequence)

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

	measure = len

	def transition(self, len=len):
		# filter empty transfers
		measure = 0

		alloc = self.next()
		measure = self.transferring = self.measure(alloc)
		self.transferred = 0

		self.emit(alloc)

	def exited(self, event):
		# Called by the Sensor.

		measure = self.measure(event)
		self.transferred += measure

		if self.transferring is None or self.transferred == self.transferring:
			self.transferred = 0
			self.transferring = None
			self.transition()

class Allocator(Meter):
	"""
	Transformer that continually allocates memory for the downstream Transformers.

	Used indirectly by &Detour instances that reference an input transit.
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
		"Transition in the next buffer provided that the Flow was not obstructed."

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
		"Continue allocating memory for &Detour transformers."

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

		s = "<%s q:%r items %r length; buf: %r of %r at %s>" %(
			self.__class__.__name__,
			qlen, qsize, xfer, bufsize,
			hex(id(self)),
		)

		return s

	@property
	def overflow(self):
		"Queue entries exceeds limit."
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
			self.controller.clear(self)

	def drain(self):
		if self.queue or self.transferring is not None:
			return functools.partial(self.__setattr__, 'draining')
		else:
			# queue is empty
			return None

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
				self.controller.obstruct(self, None,
					Condition(self, ('overflow',))
				)

def Sensor(transformer):
	"Generator that communicates transfers to the given Transformer"

	event = (yield None)
	exited = transformer.exited

	while True:
		exited(event)
		event = (yield (event,))

def meter_input(detour, transports=None, allocate=Allocator.allocate_byte_array):
	"Create the necessary Transformers for metered input."

	meter = Allocator(allocate)
	g = Sensor(meter)

	if transports:
		return (meter, detour, Functional.generator(g), Transports(), Composition())
	else:
		return (meter, detour, Functional.generator(g), Composition())

def meter_output(detour, transports=None):
	"Create the necessary Transformers for metered output."

	meter = Throttle()
	g = Sensor(meter)

	if transports:
		return (Composition(), Transports(), meter, detour, Functional.generator(g))
	else:
		return (Composition(), meter, detour, Functional.generator(g))

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

# A condition that will never be true.
Inexorable = Condition(builtins, ('False',))

class Flow(Processor):
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

	# XXX: add __slots__ to Flow

	obstructions = None
	monitors = None
	terminating = False
	terminated = False
	draining = False

	class Exits(object):
		"""
		Class for adapting Flow emits into exit signals for coroutines.

		While somewhat expensive as the callback is repeatedly configured,
		it can be efficient enough in cases where events are properly
		aggregated in order to reduce the frequency of transitions.
		"""

		__slots__ = ('events', 'callback')

		def __init__(self, Queue=collections.deque):
			self.events = Queue()

		def process(self, event, source=None):
			self.events.append(event)
			if self.callback:
				self.transition()

		def atexit(self, cb):
			self.callback = cb
			if self.events:
				self.transition()

		def transition(self):
			self.callback(self.events.popleft())
			self.callback = None

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

	def connect_exit(self):
		"""
		Construct an &AtExit instance and connect the Flow's emit
		to it. Used by &Coroutine instances to receive Flow events.
		"""

		ae = self.AtExit()
		self.emit = ae.process
		return ae

	def connect(self, flow, partial=functools.partial):
		"""
		Connect the Flow to the given object support the Flange interface.
		Normally used with other Flows, but other objects may be connectable.

		Downstream is not notified of upstream obstructions. Events run
		downstream and obstructions run up.
		"""

		# Downstreams do not need to be notified of upstream obstructions.
		# Even with output rate constraints, there is no need to apply
		# constraints if the write buffer is usually empty.

		# Events run downstream, obstructions run upstream.

		self.dependent = flow
		flow.watch(self.obstruct, self.clear)
		self.emit = flow.process

		# cascade termination; downstream is terminated by upstream
		self.atexit(partial(flow.terminate, self))

	def __repr__(self):
		links = ' -> '.join(['[%s]' %(repr(x),) for x in self.sequence])
		return '<' + self.__class__.__name__ + '[' + hex(id(self)) + ']: ' + links + '>'

	def structure(self):
		"""
		Reveal the Transformers as properties.
		"""

		sr = ()
		s = self.sequence
		p = [
			x for x in [
				('obstructions', self.obstructions),
				('monitors', self.monitors),
			] if x[1] is not None
		]
		p.extend([
			(i, s[i]) for i in range(len(s))
		])

		return (p, sr)

	sequence = ()
	def requisite(self, *transformers):
		"""
		Construct the transformer sequence for operating the flow.
		"""

		for x in transformers:
			x.subresource(self)

		transformers[-1].emit = self.emission # tie the last to Flow's emit

		for x, y in zip(transformers, transformers[1:]):
			x.emit = y.process

		self.sequence = transformers

	def actuate(self):
		"""
		Actuate the Transformers placed in the Flow by &requisite.
		"""

		super().actuate()

		for transformer in self.sequence:
			transformer.actuate()

	@property
	def obstructed(self):
		"""
		Whether or not the &Flow is obstructed.
		"""

		return self.obstructions is not None

	@property
	def permanent(self) -> int:
		"""
		Whether or not there are Inexorable obstructions present.
		An integer specifying the number of &Inexorable obstructions or &None
		if there are no obstructions.
		"""
		if self.obstructions:
			return sum([1 if x[1] is Inexorable else 0 for x in self.obstructions.values()])

	def obstruct(self, by, signal=None, condition=None):
		"""
		Instruct the Flow to signal the cessation of transfers.
		The cessation may be permanent depending on the condition.
		"""
		global Inexorable

		if not self.obstructions:
			first = True
			if self.obstructions is None:
				self.obstructions = {}
		else:
			first = False

		self.obstructions[by] = (signal, condition)

		if first and self.monitors:
			# only signal the monitors if it wasn't already obstructed.
			for sentry in self.monitors:
				sentry[0](self)

	def clear(self, obstruction):
		"""
		Clear the obstruction by the key given to &obstruction.
		"""

		if self.obstructions:
			del self.obstructions[obstruction]

			if not self.obstructions:
				self.obstructions = None

				# no more obstructions, notify the monitors
				if self.monitors:
					for sentry in self.monitors:
						sentry[1](self)

	def watch(self, obstructed, cleared):
		"""
		Assign the given functions as callbacks to obstruction events.
		First called when an obstruction occurs and second when its cleared.
		"""

		if self.monitors is None:
			self.monitors = set()
		self.monitors.add((obstructed, cleared))

		if self.obstructed:
			obstructed(self)

	def ignore(self, obstructed, cleared):
		"""
		Stop watching the Flow's obstructed state.
		"""

		self.monitors.discard((obstructed, cleared))

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
				self.obstruct(self.__class__.drain, None, clear_when)

			# initiate drain
			return self.drains(0)

	def drains(self, index, arg=None, partial=functools.partial):
		"""
		! INTERNAL:
			Drain state callback.

		Maintains the order of transformer drain operations.
		"""

		for i in range(index, len(self.sequence)):
			xf = self.sequence[i]
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
				self.clear(self.__class__.drain)

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

		for x in self.sequence:
			x.terminate()

		self.obstruct(self.__class__.terminate, None, Inexorable)
		self.controller.exited(self)

	def terminate(self, by=None):
		"""
		Drain the Flow and finish termination by signalling the controller
		of its exit.
		"""

		if self.terminated or self.terminating:
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
			return

		super().interrupt(by)
		self.process = self.discarding

		for x in self.sequence:
			x.interrupt()

		if self.dependant:
			self.dependant.interrupt(self)

	def discarding(self, event, source = None):
		"""
		Assigned to &process after termination and interrupt in order
		to keep overruns from exercising the Transformations.
		"""

		pass

	def process(self, event, source = None):
		"""
		Place the event into the flow's transformer sequence.

		&process takes an additional &source parameter for maintaining
		the origin of an event across tasks.
		"""

		self.sequence[0].process(event)

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

	def emit_manager():
		"Internal; property managing the emission of the &Flow"

		def fget(self):
			if self.sequence:
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

		doc = 'properly organize the emit setting at the edge of the flow'
		return locals()
	emit = property(**emit_manager())
	del emit_manager

# Flow that discards all events and emits nothing.
Null = Flow()
Null.sequence = (Terminal(),)

class Funnel(Flow):
	"""
	A union of events that emits data received from a set of &Flow instances.

	Funnels receive events from a set of &Flow instances and map the &Flow to a particular
	identifier that can be used by the downstream Transformers.

	Funnels will not terminate when connected upstreams terminate.
	"""

	def requisite(self, identify=lambda x: x):
		self.identify = identify

	def process(self, event, source = None):
		self.sequence[0].process((self.identify(source), event))

	def terminate(self, by=None):
		if not isisntance(by, Flow):
			super().terminate(by=by)
		# Termination induced by flow is ignored.

class Fork(Terminal):
	"""
	A &Terminal that distributes events to a set of Flows based on the identified key.

	A &Fork is the semi-inverse of &Funnel.
	"""

	def __init__(self, identify):
		self.identify = identify
		self.switch = {}

	def process(self, event):
		for flow, event in self.split(event):
			self.switch[flow].process(event, source=self)

class Iterate(Reactor):
	"""
	Reactor that sequentially emits the production of the iterator over
	a series of enqueued tasks.

	Normally used to emit predefined Flow content.

	The &Flow will be terminated when the iterator has been exhausted if
	configured to by &requisite.
	"""

	def suspend(self, by):
		"Signal an obstruction allowing &transition to break."

		self.obstructed = True

	def resume(self, flow):
		"Resume iterating."

		self.obstructed = False
		self.transition()

	@property
	def exhausted(self):
		return self.iterator == ()

	@property
	def obstructing(self):
		flow = self.controller
		if flow.obstructions:
			return self in flow.obstructions
		else:
			return False

	terminal = False
	def requisite(self, terminal:bool=False):
		"""
		[ Parameters ]

		/terminal
			Terminate the &Flow when the iterator reaches its end.
		"""

		if terminal:
			self.terminal = terminal

	def actuate(self):
		super().actuate()
		self.obstructed = False
		self.iterator = ()

	def process(self, it, source=None, iter=iter, chain=itertools.chain):
		"""
		Process the iterator replacing the current if any.
		Each iteration is treated as an individal event, so &Iterate
		is equivalent to: `map(Iterate.emit, it)`.
		"""

		if self.iterator == ():
			# new iterator
			self.iterator = iter(it)
			if self.obstructing:
				self.controller.clear(self)
		else:
			# concatenate the iterators
			self.iterator = chain(self.iterator, iter(it))

		if not self.obstructed:
			# only transition if the flow isn't obstructed
			self.transition()

	def transition(self):
		"""
		Emit the next item in the iterator until an obstruction occurs or
		the iterator is exhausted.
		"""

		for x in self.iterator:
			self.emit(x)
			if self.obstructed:
				# &resume will be called when its cleared.
				break
		else:
			self.iterator = ()

			flow = self.controller

			if self.terminal:
				flow.terminate(self)
			else:
				flow.obstruct(self, None, Condition(self, ('exhausted',)))

class Collect(Terminal):
	"""
	Data structure Transformer collecting events into a storage container.
	"""

	def __init__(self, storage, operation):
		self.storage = storage
		self.operation = operation

	@classmethod
	def list(Class):
		l = []
		return Class(l, l.append)

	@classmethod
	def dict(Class):
		d = {}
		def add(x, set=d.__setitem__):
			set(*x)
		return Class(d, add)

	@classmethod
	def set(Class):
		s = set()
		return Class(s, s.add)

	def process(self, obj):
		self.operation(obj)

class Trace(Reflection):
	"""
	Reflection that allows a set of operations to derive meta data from the Flow.
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

	def process(self, event):
		for x in self.monitors.values():
			x(event)

		self.emit(event)

	@staticmethod
	def log(event, title=None, flush=sys.stderr.flush, log=sys.stderr.write):
		"Trace monitor for printing events."
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

		self.emit(event)

class Spawn(Terminal):
	"""
	Transformer spawning Sectors using the processed events as parameters.

	Normally used as the recipient of listening sockets, this Terminal transformer
	spawns new Sectors for each item contained within a given event.
	"""

	def __init__(self, init):
		self.spawn = init

	def process(self, packet):
		"""
		Given a &packet that is a pair consisting of the source and the actual event,
		spawn a set of Resources using the initialized &spawn function.

		For listening Flows, the actual event is a sequence of accepted file descriptors.
		"""

		self.spawn(self, packet)

class Serialize(Extension):
	"""
	Serialize a set of flows in the enqueued order.

	Emulates parallel operation by facilitating the sequenced delivery of
	a sequence of flows where the first flow is carried until completion before
	the following flow may be processed.

	Essentially, this is a buffer array that uses Flow termination signals
	to manage the current working flow and queues to buffer the events to be emitted.

	Untested: recursive transition() calls.
	"""

	def __init__(self, state_function, Queue=collections.deque):
		self.state_function = state_function

		self.queues = dict() # open queues that are not next in line
		self.flows = dict()
		self.order = Queue() # queue of contexts

		# front is a Flow and context represents the headers of the Flow
		self.front = None
		self.layer = None
		self.state = None

		self.output = None

	def requisite(self, flow, state=None):
		# no inheritance; protocols refer to flows, they do not control them
		self.output = flow

	def suspend(self, flow):
		if flow is self.front:
			# front of line obstructed
			# obstruct the output
			self.output.obstruct(flow, None, Condition(flow, ('obstructed',)))

		# only the front blocks the primary flow
		# the enqueued q's will cause obstructions to
		# be inherited when they are the focus

	def resume(self, flow):
		if flow is self.front and self.output.obstructed:
			# clear our obstruction on the output
			self.output.clear(flow)

	def overflowing(self, flow):
		"Whether the given flow's queue has too many items."

		q = self.queues.get(flow)

		if q is None:
			# front flow does not have a queue
			return False
		elif len(q) > 8:
			return True
		else:
			return False

	def process(self, events, source, len=len):
		"Emit point for Sequenced Flows"

		if source is self.front:
			self.state.send(events)
		else:
			q = self.queues.get(source, None)
			if q is not None:
				q.append(events)
				if not source.obstructed and self.overflowing(source):
					source.obstruct(self, None, Condition(self, ('overflowing',), source))
			else:
				raise Exception("flow has not been connected")

	def enqueue(self, layer, Queue=collections.deque, partial=functools.partial):
		"Connect the given flow to enqueue events until it becomes the front of the line."

		if self.layer is not None:
			self.order.append(layer)
			self.queues[(Layer, layer)] = Queue()
			self.flows[layer] = None
		else:
			self.layer = layer
			self.front = None

	def connect(self, layer, flow, StopIteration=StopIteration, Queue=collections.deque):
		"Connect the flow to the given layer signalling that its ready to flow."

		if layer == self.layer:
			self.front = flow
			self.state = self.state_function(layer, self.output.process)
			try:
				next(self.state)
			except StopIteration:
				# immediate exit means there's no content according
				# to the layer context; transition the front off and return
				if flow is not None:
					flow.interrupt()

				self.transition()
				return

			# Generator did not exit; flow exit must trigger transition
			flow.atexit(self.transition)
		else:
			# not the front, so allocate queue
			self.queues[flow] = self.queues.pop((Layer, layer))
			self.flows[layer] = flow

		flow.watch(self.suspend, self.resume)
		flow.emit = self.process

	def transition(self, exiting_flow=None, getattr=getattr):
		"""
		Move the first enqueued flow to the front of the line;
		flush out the buffer and remove ourselves as an obstruction.
		"""

		terminal = getattr(self.layer, 'terminal', False)
		self.state.close() # signal end of flow to the state
		self.output.clear(self.front)
		self.front = None
		self.layer = None

		if terminal:
			# layer context identified as final
			self.output.terminate(self)
			assert not self.order

		# all events from the front should be in the output flow at this point

		if not self.order:
			# nothing to do
			return

		# front of line, no buffer necessary
		l = self.order.popleft()
		self.layer = l

		f = self.flows.pop(l)
		if f is None:
			# no flow, queue must be empty
			self.queues.pop((Layer, l), None)
			return

		q = self.queues.pop(f)
		self.state = self.state_function(l, self.output.process)
		next(self.state)

		send = self.state.send
		p = q.popleft
		while q:
			send(p())
		self.front = f

		if f.obstructed:
			# new front of line is obstructed
			# unconditionally clear self from it
			f.clear(self)

		# exit of new flow triggers transition
		f.atexit(self.transition)

class Distribute(Extension):
	"""
	Distribute input flow to a set of flows associated with
	the identified Layer Context.
	"""

	def __init__(self, Layer, state, accept, close):
		self.state_function = state
		self.queues = dict()
		self.flows = dict()

		# callback
		self.accept_callback = accept
		self.close_callback = close

		# state is continuous.
		self.state = self.state_function(Layer, self.accept, self.transport, self.close)
		next(self.state)

		self.flow = None
		self.layer = None

	def requisite(self, input):
		self.input = input

	def process(self, events, source = None, partial=functools.partial):
		Protocol = self.controller
		Protocol.context.enqueue(partial(self.state.send, events))

	def connect(self, layer, flow):
		"""
		Associate the flow with the Layer Context allowing transfers into the flow.
		"""

		self.flows[layer] = flow
		self.drain(layer)

		# the availability of the flow allows the queue to be dropped
		del self.queues[layer]

	def drain(self, layer):
		"""
		Drain the queue associated with the layer into the connected Flow.
		"""

		q = self.queues[layer]
		fp = self.flows[layer].process
		p = q.popleft

		while q:
			fp(p(), source=self)

	def transport(self, layer, events):
		"""
		Enqueue or transfer the events to the flow associated with the layer context.
		"""

		f = self.flows.get(layer)
		if f is None:
			self.queues[layer].append(events)
			# block if overflow
		else:
			self.flows[layer].process(events, source=self)

	def close(self, layer):
		"""
		End of Layer context content. Flush queue and remove entries.
		"""

		if layer.content and layer in self.flows:
			# flush q if necessary
			if layer in self.queues:
				# This branch doesn't happen
				# in cases where the head of the line
				# has already connected a flow. (queue is removed)
				self.drain(layer)
				del self.queues[layer]

			flow = self.flows.pop(layer)
		else:
			flow = None
		# otherwise, no q and no flow; layer context only

		self.close_callback(layer, flow)

		if getattr(layer, 'terminal', False):
			self.input.terminate()

	def accept(self, layer, Queue=collections.deque):
		"""
		Initialize a Layer context allowing events to be queued until a Flow is connected.
		"""

		if layer.content:
			self.flows[layer] = None
			self.queues[layer] = Queue()

		self.accept_callback(layer)

class QueueProtocol(Protocol):
	"""
	Queue based protocol. Used for supporting protocols like HTTP 1.1 and SMTP.

	The &connect and &accept methods are the primary interface points for
	instances; &connect being used by clients and &accept being used by servers.
	The distinction between the two operations center around a client's need to
	know what the response Layer Context object will be without having to use
	state to associate a request with an incoming response.
	"""

	def structure(self):
		p = [
			('distribute.input', self.distribute.input),
			('serialized.output', self.serialize.output),
		]
		sr = []

		return (p, sr)

	def __init__(self,
			InputLayer, OutputLayer,
			protocol_input_state,
			protocol_output_state,
		):
		"""
		Create a QueueProtocol instance using the
		&Layer classes for input and output of protocol messages, and
		from the input and output generators that transform protocol
		specific signals into &QueueProtocol state transitions.
		"""

		self.distribute = None
		self.serialize = None
		self.exits = 0

		# Protocol defining parts
		self.input_layer = InputLayer
		self.output_layer = OutputLayer
		self.protocol_input = protocol_input_state
		self.protocol_output = protocol_output_state

	def requisite(self, accept, close, input, output):
		"""
		Configure the I/O flows for the protocol.
		"""

		s = self.serialize = Serialize(self.protocol_output)
		s.subresource(self)

		# reads need to know how to affix
		d = self.distribute = Distribute(self.input_layer, self.protocol_input, accept, close)
		d.subresource(self)

		input.emit = d.process

		s.requisite(output)
		d.requisite(input)
		input.atexit(self.dependency_exit)
		output.atexit(self.dependency_exit)

	def dependency_exit(self, flow):
		"""
		Called when either the input or output flow exits.
		"""

		if self.exits:
			self.terminated = True
			self.terminating = False
			self.controller.exited(self)

		self.exits += 1

class ParallelProtocol(Protocol):
	"""
	Parallel Channel Protocol. Used for supporting protocols like HTTP 2.0.
	"""

import codecs
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

	emit = transformer.emit
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
del codecs

class Circulation(Device):
	"""
	Unit device for broadcasting and messaging to other sector daemons.

	Circulation is used to support message passing to worker processes of the same service
	across processes, machines, and sites.
	"""

	def actuate(self):
		"""
		Acquire the ports used to facilitate communication.
		"""
		ports = self.controller.ports

		site = ports.acquire('site')

class Ports(Device):
	"""
	Listening Ports Device.

	&Ports manages the set of listening sockets used by a &Unit.
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
				if x.route.exists() and x.route.type() == "socket":
					x.route.void()

		for ep, fd in zip(endpoints, self.context.bindings(*endpoints)):
			add(ep, fd)

	def acquire(self, slot):
		"""
		Acquire a set of listening &Transformer instances.
		Each instance should be managed by a &Flow that constructs
		the I/O &Transformer instances from the received socket connections.

		Internal endpoints are usually managed as a simple transparent relay
		where the constructed Relay instances are simply passed through.
		"""

		ports = self.sets[slot]
		del self.sets[slot]

		return ports

	def load_environment(self, slots, prefix="FIOD_"):
		"""
		Load the slots stored in the environment into the &Ports instance.
		The Environment variables referenced have the following consistency:

		The root variable is a list of slot identifiers stored:

		#!
			PREFIX+"_DEVICE_PORTS_SLOTS"=slot_id1, slot_id2, ..., slot_idN

		The slots are defined with a pair of variables:

		#!
			PREFIX+"_SLOT_PORTS_"+SLOT_ID=fd1,fd2,...,fdN
			PREFIX+"_SLOT_BINDS_"_SLOT_ID=type address port, ..., typeN addressN portN

		The slot ports are the file descriptors, and the slot binds are the endpoints
		that were used to create the file descriptor.
		"""

		raise NotImplementedError

	def render_envrionment(self, slots, len=len, zip=zip, int=int):
		"""
		Load the inherited sockets.
		"""

		global endpoint
		env = self.context.environ

		sif = env(self.prefix + "INTERFACES")
		if sif is None:
			return

		# FIO_S_INTERFACES=http,https,ftp
		for ifs in sif.split(","):
			ifset = self.sets[ifs]

			bindings = env("FIOD_IB_"+ifs).split(",")
			sockets = env("FIOD_IS_"+ifs).split(",")

			if len(bindings) != len(sockets):
				raise RuntimeError("invalid interfaces environment configuration")

			for socket, binding in zip(sockets, bindings):
				typ, addr, port = binding.split(' ')
				ifset[endpoint(typ, addr, port)] = int(socket)

	def store_environment(self, slots, prefix="FIOD_"):
		"""
		Save the slots in &Ports instance into the environment in preparation
		"""

		os.environ.update(self.render_environment(slots))

class Locks(Device):
	"""
	Locks Device.

	Manages the set of synchronization primitives used by a process. Usually
	used by sector daemons to manage advisory locks.
	"""

	device_entry = 'locks'
