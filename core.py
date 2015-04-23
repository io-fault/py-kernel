"""
Core classes, exceptions, and data.
"""
import array
import weakref
import collections
import functools

from ..fork import libhazmat

# Indirect association of Logical Process objects and Programs.
__process_index__ = dict()

# Indirect association of Logical Process objects and traffic Interchanges.
# Interchange holds references back to the process.
__traffic_index__ = dict()

def dereference_controller(self):
	return self.controller_reference()

def set_controller_reference(self, obj, Ref = weakref.ref):
	self.controller_reference = Ref(obj)

def get_location(self):
	if self.location_path is not None:
		# object is at the index
		return self.location_path
	else:
		# object is contained by an indexed object?
		if self.controller is not None:
			return self.controller.location

	# object is not "in" a program
	return None

def set_location(self, path):
	self.location_path = path

class Resource(object):
	"""
	Base class for objects managed by a LogicalProcess.
	"""
	context = None
	location_path = None
	controller_reference = lambda: None

	controller = property(
		fget = dereference_controller,
		fset = set_controller_reference,
		doc = "controller property for process objects"
	)

	location = property(
		fget = get_location,
		fset = set_location,
		doc = "get and set the location path of a process object"
	)

	@property
	def initializing(self):
		if self.controller is None:
			return True

	def inherit(self, ascent):
		"""
		Inherit the context and location, and assign &ascent as the controller.
		"""
		self.controller_reference = weakref.ref(ascent)
		self.context = ascent.context
		self.location_path = self.controller.location_path

class Protocol(Resource):
	"""
	A class used to manage and represent protocol state.
	"""
	name = None

class Transformer(Resource):
	"""
	A Transformer is a unit of state that produces change in a Flow.
	"""
	def process(self, data):
		self.emit(data)

	def emit(self, data):
		raise RuntimeError("emit property was not set to following transformer")

class Funnel(Transformer):
	"""
	A Join that emits data received from a set of @Flow's.
	"""
	def __init__(self, identify):
		self.identify = identify

	def process(self, event, source = None):
		self.emit((self.identify(source), event))

class Terminal(Transformer):
	"""
	A Transformer that never emits.
	"""
	def process(self, item):
		pass

class Join(Transformer):
	"""
	A Transformer that explicitly relies on side-effects in order to emit events.
	"""

class Processor(Join):
	"""
	A Processor that applies the function in a general purpose thread and enqueues the
	emission to the process' task queue.
	"""
	enqueue = None
	dispatch = None

	def install(self, function, serialization = None, partial = functools.partial):
		self.function = function
		self.serialization = serialization

		self.enqueue = self.context.enqueue
		self.dispatch = self.context.dispatch

		if self.serialization is None:
			self.method = partial(self.imperfect, self.function)
		else:
			self.method = partial(self.serializing, self.function)

	@classmethod
	def serialized(Class, function):
		"""
		Create a Parallel processor instance that guarantees serialization of processing
		operations.
		"""
		return Class(function, libhazmat.create_knot())

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

class Generator(Processor):
	"""
	A Processor that sends events to the generator.
	"""
	def install(self, function):
		self.generator = function(self)
		super().install(self.generator.send, serialization = libhazmat.create_knot())
		self.generator_function = function

		next(self.generator)

	def emission(self, event, partial = functools.partial):
		"""
		A means to vent emission before yielding out of a generator.
		"""
		print('gxf emission', self.emit)
		return self.enqueue(partial(self.emit, event))

	def serializing(self, function, event):
		# inside a general purpose thread
		with self.serialization:
			# trap exceptions while serializing.
			try:
				# generators call emission directly
				result = function(event)
			except StopIteration:
				# XXX: signal obstruction or interruption?
				pass

class References(Join):
	"""
	Collection of &Object references. Used to hold objects until their explicit removal
	from the program.
	"""
	mechanisms = {
		'python:dict': dict,
	}

	def __init__(self, identifier = None, Mechanism = dict):
		self.port = None
		self.storage = Mechanism()
		self.index = Mechanism()
		x = "ps://program/dir/dir/item#213213242"

	def access(self, key):
		"""
		Return the object assigned to the given key.
		"""
		if key in self.index:
			return self.index[key]

	def process(self, obj, identifier = None):
		"""
		Add the given object to the set of references.
		"""
		if identifier is not None:
			obj.identifier = identifier

		self.storage[obj] = identifier
		self.index[identifier] = obj

	def emit(self, obj):
		"""
		Remove the object from the set of references.
		"""
		key = self.storage.pop(obj, None)
		self.index.pop(key, None)

class Link(Join):
	"""
	A symbolic link to an arbitrary &Object.

	When used as a Transformer, the Link will send events to their target.
	"""
	def __init__(self, target, *subpath, Mechanism = lambda x: x):
		self.target = Mechanism(target)
		self.subpath = subpath # attribute path on controller

	def dereference(self):
		"""
		Return the referenced object.
		"""
		return self.target

	def process(self, event):
		self.dereference().process(event)

	def emit(self):
		"""
		Links do not emit; the processed objects will be sent to be processed by
		their target.
		"""
		pass

class Detour(Join):
	"""
	Transformer moving received events through a transit and back into the
	flow that the Loop is participating in.

	Essentially, this is an @Intersection with the guarantee that cumulative events
	will make its way to the next Transformer saving cases of errors.
	"""
	Queue = collections.deque

	def __init__(self):
		self.transit = None
		self.queue = None # None means that the transit does not have a working resource.

	def install(self, transit):
		self.transit = transit
		transit.link = self

	def transition(self):
		q = self.queue
		acquire = self.transit.acquire
		buf = None

		# often called from the traffic side, consume
		# the next item while filtering empty acquires
		while q:
			buf = q.popleft()
			if buf:
				acquire(buf)

				# XXX stopgap for constraint based obstructions
				if len(self.queue) < 2 and self.controller.obstructed:
					self.controller.clear(self)
				break
		else:
			self.queue = None
			# stop minimum rate checks
		del buf

	def emission(self, event):
		"""
		Perform the emission.
		"""
		transfer_size = len(event)
		self.emit((event,))

	def process(self, event):
		# the part of the io loop that modifies q state
		# is ran in the main task q. we are guaranteed exclusive access
		# to the state of the detour instance

		if self.queue is None:
			# no working queue so create one,
			# and run a transition directly
			if event:
				self.queue = self.Queue(event)
				self.transition()
		else:
			# the transit will run transitions (thread or io)
			self.queue.extend(event)

		if len(self.queue) > 4:
			self.controller.obstruct(self, None)

# XXX: use a resizeable pool for memory sources instead of an infinite supply
# currently this is a stopgap as constraints aren't available yet.
class Memory(object):
	resource_allocate = {
		'int': (array.array("i", [-1]).__mul__, 24),
		'octet': (bytearray, 1024)
	}

	def __init__(self, flow, mtype = 'octet'):
		self.allocate, self.size = self.resource_allocate[mtype]
		flow.watch(self.stop, self.supply)

	def stop(self, flow):
		pass

	def supply(self, flow):
		while not flow.obstructed:
			flow.process([self.allocate(self.size) for x in range(4)])

class Connection(Join):
	"""
	Represents a local or remote connection or binding.
	"""
	transmission = None
	protocol = None
	interface = None # *local* interface (bind address)
	route = None # remote address or proxy series

class Stream(Connection):
	"""
	A unidirectional stream of arbitrary Python objects.
	"""
	def __init__(self):
		self.flow = Flow()
		self.protocol = None
		self.identifiers = list()
		# XXX: hard coding the allocation
		self.source = Memory(self.flow, mtype = 'int')

	def process(self, event):
		return self.flow.process(event)

class IO(Connection):
	"""
	A bidirectional stream of arbitrary Python objects.
	The primary interface for performing I/O.

	An associated pair of @Flow's.
	Usually a bidirectional channel like a socket connection.
	"""
	@property
	def input(self):
		return self.flows[0]

	@property
	def output(self):
		return self.flows[1]

	def __init__(self):
		self.identifiers = []
		self.flows = (Flow(), Flow())
		self.source = Memory(self.flows[0])
		# XXX need a real pool fed by a Context

	def inherit(self, ascent):
		super().inherit(ascent)
		self.flows[0].inherit(self)
		self.flows[1].inherit(self)

	def install(self, start):
		self.stack('endpoint', start[0], start[1])

	def finish(self):
		"""
		Instruct the flows to finish according to the order that they appear
		in &self.flows.
		"""
		for flow in self.flows:
			flow.finish()

	def process(self, event):
		self.output.process(event)

	def emit_manager():
		def fget(self):
			return self.input.emit
		def fset(self, val):
			# given that IO is inserted into a flow
			self.input.emit = val
		doc = 'properly relay the emit setting to the input flow'
		return locals()
	emit = property(**emit_manager())

class Flow(Resource):
	"""
	A transformation sequence.
	"""
	obstructions = None
	sentries = None

	def __init__(self):
		self.sequence = () # transformers

	def attach(self, context):
		self.context = context

	@property
	def obstructed(self):
		return self.obstructions is not None

	def obstruct(self, by, signal, condition = None):
		if not self.obstructions:
			first = True
			if self.obstructions is None:
				self.obstructions = {}
		else:
			first = False
		self.obstructions[by] = (signal, condition)

		if first and self.sentries:
			for sentry in self.sentries:
				sentry[0](self)

	def clear(self, obstruction):
		"""
		Clear the obstruction by the key given to @obstruct.
		"""
		if self.obstructions:
			del self.obstructions[obstruction]

		if not self.obstructions:
			self.obstructions = None

			# no more obstructions, notify the sentries
			for sentry in self.sentries:
				sentry[1](self)

	def watch(self, obstructed, cleared):
		if self.sentries is None:
			self.sentries = set()
		self.sentries.add((obstructed, cleared))

		if self.obstructed:
			obstructed(self)

	def configure(self, *transformers):
		"""
		Construct the transformer sequence for operating the flow.
		"""
		for x in transformers:
			x.inherit(self)

		transformers[-1].emit = self.emission

		for x, y in zip(transformers, transformers[1:]):
			x.emit = y.process

		self.sequence = transformers

	def process(self, event, source = None):
		"""
		Place the event into the flow's transformer sequence.
		"""
		self.sequence[0].process(event)

	def continuation(self, event, source = None):
		"""
		Receives events from the last Transformer in the sequence.
		Defaults to throwing the event away, but overridden when
		connected to another flow.
		"""
		pass

	def emission(self, event):
		return self.continuation(event, source = self) # identify flow as source

	def emit_manager():
		"""
		"""
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
