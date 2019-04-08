"""
# Channel Processors used to construct conceptual Flows.

# A &Channel represents an individual segment in a conceptual Flow. Channels
# connect together like UNIX pipes, but transfer typed messages (objects) instead
# of just data.
"""
import sys
import array
import collections
import functools
import weakref
import typing
import queue

from . import core

# Little like an enum, but emphasis on the concept rather than enumeration.
class Event(object):
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

fe_initiate = Event.initiate = Event()
fe_clear = Event.clear = Event()
fe_transfer = Event.transfer = Event()
fe_obstruct = Event.obstruct = Event()
fe_terminate = Event.terminate = Event()
fe_overflow = Event.overflow = Event()

Event.operations = (
	Event.terminate,
	Event.obstruct,
	Event.transfer,
	Event.clear,
	Event.initiate,
)

class Channel(core.Processor):
	"""
	# A Processor consisting of an arbitrary set of operations that
	# can connect to other &Channel instances in order to make a series
	# of transformations.

	# Channels are the primary mechanism used to stream events; generally,
	# anything that's a stream should be managed by &Channel instances in favor
	# of other event callback mechanisms.

	# [ Properties ]

	# /f_type/
		# The flow type describing what the instance does.
		# This property can be &None at the class level, but should be initialized
		# when an instance is created.

		# /(id)`source`/
			# Channel that primarily emits events for downstream processing.
		# /(id)`terminal`/
			# Channel processes events, but emits nothing.
		# /(id)`switch`/
			# Channel that takes events and distributes their transformation
			# to a mapping of receiving flows. (Diffusion)
		# /(id)`join`/
			# Channel that receives events from a set of sources and combines
			# them into a single stream.
		# /(id)`transformer`/
			# Channel emits events strictly in response to processing. Transformers
			# may buffer events as needed.
		# /&None/
			# Unspecified type.

	# /f_obstructions/
		# /&None/
			# No obstructions present.
		# /&typing.Mapping/
			# The objects that are obstructing the &Channel from
			# performing processing associated with the exact
			# condition causing it.

	# /f_monitors/
		# The set of callbacks used to signal changes in the flow's
		# &f_obstructed state.

		# /&None/
			# No monitors watching the flow state.

	# /f_downstream/
		# The &Channel instance that receives events emitted by the instance
		# holding the attribute.
	"""

	f_type = None
	f_obstructions = None
	f_monitors = None
	f_downstream = None
	f_upstream = None

	def f_connect(self, flow:core.Processor, partial=functools.partial, Ref=weakref.ref):
		"""
		# Connect the Channel to the given object supporting the &Flow interface.
		# Normally used with other Channels, but other objects may be connected.

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
		self.f_emit = flow.f_transfer

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
		# Connect the upstream to the downstream leaving the Channel &self
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
		# Reveal the obstructions and monitors of the Channel.
		"""

		sr = ()
		p = [
			x for x in [
				('f_obstructions', self.f_obstructions),
				('f_monitors', self.f_monitors),
			] if x[1] is not None
		]

		return (p, sr)

	def terminate(self, by=None):
		"""
		# Drain the Channel and finish termination by signalling the controller
		# of its exit.
		"""

		if self.terminated or self.terminating or self.interrupted:
			return False

		self.terminator = by
		self.start_termination()

		self.enqueue(self._f_terminated)
		return True

	def f_terminate(self):
		"""
		# Termination signal received when the upstream no longer has
		# flow transfers for the downstream Channel.
		"""
		self._f_terminated()

	def _f_terminated(self):
		"""
		# Used by subclasses to issue downstream termination and exit.

		# Subclasses must call this or perform equivalent actions when termination
		# of the conceptual flow is complete.
		"""

		self.f_transfer = self.f_discarding
		self.f_emit = self.f_discarding

		if self.f_downstream:
			self.f_downstream.f_ignore(self.f_obstruct, self.f_clear)
			self.f_downstream.f_terminate()

		self.finish_termination()

	def interrupt(self):
		self.f_transfer = self.f_discarding
		self.f_emit = self.f_discarding

		if self.f_downstream:
			# XXX: interrupts should not terminate the flow
			# However, &Relay will terminate the receiver.

			# interrupt the downstream and
			# notify exit iff the downstream's
			# controller is functioning.
			ds = self.f_downstream
			ds.f_terminate()
			dsc = ds.controller
			if dsc is not None and dsc.functioning:
				dsc.exited(ds)

		self.interrupted = True

	def f_transfer(self, event, source=None):
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

		# This property returns &True in cases where the Channel's
		# state is such that it may independently send events downstream.

		# Channels that have buffers *should* implement this method.
		"""

		return True

	@property
	def f_obstructed(self):
		"""
		# Whether or not the &Channel is obstructed.
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
		# Instruct the Channel to signal the cessation of transfers.
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

class Terminal(Channel):
	"""
	# Transparent channel that performs a callback when termination
	# is received from the upstream channel.

	# Used as an atexit callback for flows.
	"""

	def __init__(self, endpoint):
		self.t_endpoint = endpoint

	def f_terminate(self, by=None):
		if self.terminated:
			return

		self._f_terminated()
		self.t_endpoint(self)

class Relay(Channel):
	"""
	# Relay intersector transfers.

	# Initialized with the set of events that will be relayed,
	# &fe_transfer, &fe_terminate, and &fe_interrupt.
	"""

	def __init__(self, integral, key):
		self.r_integral = integral
		self.r_key = key

	def f_transfer(self, event, source=None):
		self.r_integral.int_transfer(self.r_key, event)
		self.f_emit(event)

	def interrupt(self):
		self.r_integral.int_interrupt(self.r_key)
		super().interrupt()

	def f_terminate(self, by=None):
		self.r_integral.int_terminate(self.r_key)
		super().f_terminate()

class Receiver(Channel):
	"""
	# Receive intersector transfers.

	# A simple &Channel expecting to receive events from a remote &Relay or &Inlet.
	# For &Inlet, key parameters are ignored.
	"""

	# Support for single integration receiver.
	def int_transfer(self, key, event):
		self.f_emit(event)

	def int_interrupt(self, key):
		self.interrupt()

	def int_terminate(self, key):
		self.f_terminate()

class Inlet(Channel):
	"""
	# A &Relay that uses integration interfaces to send flow events.

	# Like &Relay, events are sent downstream after they have been relayed
	# to the remote integral.
	"""

	def __init__(self, integral, key):
		self.i_integral = integral
		self.i_key = key

	def f_transfer(self, event):
		self.i_integral.int_transfer(self, event)
		self.f_emit(event)

	def interrupt(self):
		self.i_integral.int_interrupt(self)
		super().interrupt()

	def f_terminate(self):
		self.i_integral.int_terminate(self)
		super().f_terminate()

class Mitre(Channel):
	"""
	# The joining flow between input and output.

	# Subclasses of this flow manage the routing of protocol requests.
	"""
	f_type = 'mitre'

	def f_connect(self, flow:core.Processor):
		"""
		# Connect the given flow as downstream without inheriting obstructions.
		"""

		# Similar to &Channel, but obstruction notifications are not carried upstream.
		self.f_downstream = flow
		self.f_emit = flow.f_transfer

class Sockets(Mitre):
	"""
	# Mitre for transport flows created by &System in order to accept sockets.
	"""

	def __init__(self, reference, router):
		self.m_reference = reference
		self.m_router = router

	def f_transfer(self, event, source=None):
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

class Transformation(Channel):
	"""
	# A flow that performs a transformation on the received events.
	"""

	def __init__(self, transform):
		self.tf_transform = transform

	def f_transfer(self, event, source=None):
		self.f_emit(self.tf_transform(event))

	terminate = Channel._f_terminated

class Iteration(Channel):
	"""
	# Channel that emits the contents of an &collections.abc.Iterator until
	# an obstruction occurs or the iterator ends.
	"""
	f_type = 'source'

	def f_clear(self, *args) -> bool:
		"""
		# Override of &Channel.f_clear that enqueues an &it_transition call
		# if it's no longer obstructed.
		"""

		if super().f_clear(*args):
			self.enqueue(self.it_transition)
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
			self.f_emit(x)
			if self.f_obstructed:
				# &f_clear will re-queue &it_transition after
				# the obstruction is cleared.
				break
		else:
			self._f_terminated()

	def __init__(self, iterator):
		"""
		# [ Parameters ]

		# /iterator/
			# The iterator that produces events.
		"""

		self.it_iterator = iter(iterator)

	def actuate(self):
		if not self.f_obstructed:
			self.enqueue(self.it_transition)

	def f_transfer(self, it, source=None):
		"""
		# Raises exception as &Iteration is a source.
		"""
		raise Exception('Iteration only produces')

class Collection(Channel):
	"""
	# Terminal &Channel collecting the events into a buffer for processing after
	# termination.
	"""
	f_type = 'terminal'

	def __init__(self, storage, operation):
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

	def f_transfer(self, obj, source=None):
		self.c_operation(obj)

class Parallel(Channel):
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

		self.start_termination()
		self._pf_put(None)
		return True

	def trap(self):
		"""
		# Internal; Trap exceptions in order to map them to faults.
		"""
		try:
			self.pf_target(self, self.pf_queue, *self.pf_parameters)
			self.enqueue(self._f_terminated)
		except BaseException as exc:
			self.enqueue(functools.partial(self.fault, exc))
			pass # The exception is managed by .fault()

	def f_transfer(self, event, source=None):
		"""
		# Send the event to the queue that the Thread is connected to.
		# Injections performed by the thread will be enqueued into the main task queue.
		"""

		self._pf_put(event)

	def actuate(self):
		"""
		# Execute the dedicated thread for the transformer.
		"""

		self.f_transfer = self._pf_put
		self.system.execute(self, self.trap)

class Transports(Channel):
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

	@classmethod
	def create(Class, transports, Stack=list):
		"""
		# Create a pair of &Protocols instances.
		"""

		i = Class(1)
		o = Class(-1)

		i._tf_opposite = weakref.ref(o)
		o._tf_opposite = weakref.ref(i)

		stack = i.tf_stack = o.tf_stack = Stack(x[0] for x in transports)

		ops = [x[1] for x in transports]
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
		self.f_transfer(())

	def terminal(self):
		self.f_transfer(())

		if not self.tf_stack:
			self._f_terminated()
			return

		if not self.tf_stack[-1].terminated:
			o = self.opposite
			if o.terminating and o.functioning:
				# Terminate other side if terminating and functioning.
				self.tf_stack[-1].terminate(-self.tf_polarity)
				o.f_transfer(())

	def f_transfer(self, events, source=None):
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

		# Termination must be checked everytime unless f_transfer() was called from here
		if opposite_has_work:
			# Use recursion on purpose and allow
			# the maximum stack depth to block an infinite loop.
			# from a poorly implemented protocol.
			self._tf_opposite().f_transfer(())
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
				if opp.f_downstream:
					opp.f_downstream.f_terminate()
					opp.f_disconnect()
		else:
			if not stack:
				# empty stack. check for terminating conditions.
				if self.terminating:
					self._f_terminated()
				if opp is not None and opp.terminating:
					opp._f_terminated()

	def f_terminate(self):
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
			self.start_termination()
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

class Funnel(Channel):
	"""
	# A union of events that emits data received from a set of &Flow instances.

	# The significant distinction being that termination from &Flow instances are ignored.
	"""

	def f_terminate(self):
		pass

class Traces(Channel):
	def __init__(self):
		self.monitors = dict()

	def monitor(self, identity, callback):
		"""
		# Assign a monitor to the Meta Reflection.

		# [ Parameters ]

		# /identity/
			# Arbitrary hashable used to refer to the callback.

		# /callback/
			# Unary callable that receives all events processed by Trace.
		"""

		self.monitors[identity] = callback

	def trace_process(self, event, source=None):
		for x in self.monitors.values():
			x(event)

		self.f_emit(event)
	f_transfer = trace_process

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

class Catenation(Channel):
	"""
	# Sequence a set of flows in the enqueued order.

	# Emulates parallel operation by facilitating the sequenced delivery of
	# a sequence of flows where the first flow is carried until completion before
	# the following flow may be processed.

	# Essentially, this is a buffer array that uses Flow termination signals
	# to manage the current working flow and queues to buffer the events to be emitted
	# when next is promoted.

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

	def int_transfer(self, source, events, fc_xfer=Event.transfer):
		"""
		# Emit point for Sequenced Flows
		"""

		# Look up layer for protocol join downstream.
		q, layer, term = self.cat_connections[source]

		if layer == self.cat_order[0]:
			# Only send if &:HoL.
			if not self.cat_events:
				self.enqueue(self.cat_flush)
			self.cat_events.append((fc_xfer, layer, events))
		else:
			if q is not None:
				q.append(events)
				if not source.f_obstructed and self.cat_overflowing(source):
					source.f_obstruct(self, None, core.Condition(self, ('cat_overflowing',), source))
			else:
				raise Exception("flow has not been connected")

	def f_transfer(self, events):
		self.cat_order.extend(events)
		return [
			(x, functools.partial(self.cat_connect, x)) for x in events
		]

	def int_terminate(self, source):
		cxn = self.cat_connections[source]
		q, layer, term = cxn

		if layer == self.cat_order[0]:
			# Head of line.
			self.cat_transition()
			# assert layer != self.cat_order[0]
		else:
			# Not head of line. Update entry's termination state.
			self.cat_connections[source] = (q, layer, True)

	def f_terminate(self):
		# Not termination from an upstream subflow.
		# Note as terminating.
		if not self.terminating:
			self.start_termination()
			self.cat_flush()

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

	def cat_connect(self, layer, flow, fc_init=Event.initiate, Queue=collections.deque):
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
				self.enqueue(self.cat_flush)
			self.cat_events.append((fc_init, layer))
			if flow is None:
				self.cat_transition()
		else:
			# Not head of line, enqueue events iff flow is not None.
			self.cat_flows[layer] = flow
			if flow is not None:
				self.cat_connections[flow] = (Queue(), layer, None)

	def cat_drain(self, fc_init=Event.initiate, fc_xfer=Event.transfer):
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
			self.enqueue(self.cat_flush)

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

	def cat_transition(self, fc_terminate=Event.terminate, exiting_flow=None, getattr=getattr):
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
			self.enqueue(self.cat_flush)
		self.cat_events.append((fc_terminate, l))

		# Drain new head of line queue.
		if self.cat_order:
			if self.cat_order[0] in self.cat_flows:
				# Connected, drain and clear any obstructions.
				self.enqueue(self.cat_drain)

class Division(Channel):
	"""
	# Coordination of the routing of a protocol's layer content.

	# Protocols consisting of a series of requests, HTTP for instance,
	# need to control where the content of a request goes. &QueueProtocolInput
	# manages the connections to actual &Flow instances that delivers
	# the transformed application level events.
	"""
	f_type = 'fork'

	def __init__(self):
		self.div_queues = collections.defaultdict(collections.deque)
		self.div_flows = dict() # connections
		self.div_initiations = []

	def f_transfer(self, events, source=None):
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

	def interrupt(self, by=None, fc_terminate=Event.terminate):
		"""
		# Interruptions on distributions translates to termination.
		"""

		# Any connected div_flows are subjected to interruption here.
		# Closure here means that the protocol state did not manage
		# &close the transaction and we need to assume that its incomplete.
		for layer, flow in self.div_flows.items():
			if flow in {fc_terminate, None}:
				continue
			flow.f_terminate()

		return True

	def f_terminate(self):
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

	def div_connect(self, layer, flow, fc_terminate=Event.terminate):
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
		fp = flow.f_transfer
		p = q.popleft

		while q:
			fp(p(), source=self) # drain division queue for &flow

		# The availability of the flow allows the queue to be dropped.
		del self.div_queues[layer]
		if cflow == fc_terminate:
			flow.f_terminate()

	def div_transfer(self, fc, layer, subflow_transfer):
		"""
		# Enqueue or transfer the events to the flow associated with the layer context.
		"""

		flow = self.div_flows[layer] # KeyError when no Event.initiate occurred.

		if flow is None:
			self.div_queues[layer].append(subflow_transfer)
			# block if overflow
		else:
			# Connected flow.
			flow.f_transfer(subflow_transfer, source=self)

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

	def div_terminate(self, fc, layer, fc_terminate=Event.terminate):
		"""
		# End of Layer context content. Flush queue and remove entries.
		"""

		if layer in self.div_flows:
			flow = self.div_flows.pop(layer)
			if flow is None:
				# no flow connected, but expected to be.
				# just leave a note for .f_connect that it has been closed.
				self.div_flows[layer] = fc_terminate
			else:
				flow.f_ignore(self.f_obstruct, self.f_clear)
				flow.f_terminate()

			assert layer not in self.div_queues[layer]

	div_operations = {
		Event.initiate: div_initiate,
		Event.terminate: div_terminate,
		Event.obstruct: None,
		Event.clear: None,
		Event.transfer: div_transfer,
		Event.overflow: div_overflow,
	}
