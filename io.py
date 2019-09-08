"""
# I/O Transaction Contexts for managing transfers and protocol transports.

# I/O is managed using three types: &Transfer, &Transport, and &Interface.
# &Transfer is the Transaction that manages the flows supporting a bidirectional or unidirecitonal
# stream.
"""
import typing
import itertools
import functools
import weakref

from . import core
from . import flows

class Transfer(core.Context):
	"""
	# Context managing a *single* sequence of &flows.Channel instances.
	"""

	def actuate(self):
		self.provide('transfer')

	_io_start = None

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

		self._io_start = weakref.ref(series[0])
		dispatch = self.sector.dispatch

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
		self._io_start().f_transfer(None)

	def io_terminate(self):
		"""
		# Explicitly terminate the managed flow.
		"""

		first = self._io_start()
		if first is not None:
			first.f_terminate()

	def _io_check_terminate(self):
		if self.xact_empty():
			self.finish_termination()
		# Dispatch timeout?

	def _io_transfer_terminated(self, terminal):
		"""
		# Complete the termination of the transfer.
		"""
		self.start_termination()
		self.enqueue(self._io_check_terminate)

	def terminate(self):
		if not self.functioning:
			return

		self.start_termination()
		self.io_terminate()

class Invocations(core.Processor):
	"""
	# Dispatch processor for &Transport instances.
	"""

	def __init__(self, catenate, router):
		self.i_catenate = catenate
		self.i_router = router
		self._protocol_xact_queue = []
		self._protocol_xact_id = 1

	def actuate(self):
		self._catapi = (self.i_catenate.int_reserve, self.i_catenate.int_connect)

	def terminate(self):
		self.finish_termination()

	def i_receive_closed(self):
		self.i_close()

	def i_dispatch(self, events):
		# Synchronized on Logical Process Task Queue
		# Point of this local task queue is to manage the stack context
		# and to (force) aggregate processing of protocol dispatch.
		xq = self._protocol_xact_queue
		already_queued = bool(xq)
		xq.extend(events)
		if not already_queued:
			self.critical(self.i_signal)

	def i_update(self, router):
		"""
		# Update the router used to facilitate a protocol transaction.
		"""
		self.i_router = router

	def i_signal(self):
		"""
		# Method enqueued by &f_transfer to flush the protocol transaction queue.
		# Essentially, an internal method.
		"""
		return self.i_router(self)

	def i_close(self):
		self.sector.xact_context.io_transmit_close()

	def _m_transition(self):
		# Must be called within same processor.
		xq = self._protocol_xact_queue
		self._protocol_xact_queue = []
		return xq

	def inv_accept(self, partial=functools.partial):
		"""
		# Accept a sequence of requests from a client configured remote endpoint.
		# Routes the initiation parameter with callbacks to connect input and output.

		# Used by routers employed by servers to get protocol transactions.
		"""

		events = self._m_transition()
		self._protocol_xact_id += len(events)

		ireserve, iconnect = self._catapi

		rl = []
		add = rl.append
		for received in events:
			channel_id = received[0]
			ireserve(channel_id)
			add(partial(iconnect, channel_id))

		return (rl, events)

	def m_correlate(self):
		"""
		# Received a set of responses. Join with requests, and
		# execute the receiver provided by the enqueueing operation.

		# Used by routers employed by clients to get the response of a protocol transaction.
		"""

		# Difference between m_accept being that outgoing channels are not reserved.
		return self._m_transition()

	def m_allocate(self, quantity=1, partial=functools.partial):
		"""
		# Allocate a channel for submitting a request.

		# Returns the channel identifier that will be used and the callback to submit the
		# initiate parameter and upstream channel.
		"""

		start = self._protocol_xact_id
		self._protocol_xact_id += quantity
		ireserve, iconnect = self._catapi

		for i in range(start, self._protocol_xact_id):
			ireserve(i)
			yield i, partial(iconnect, i)

class Transport(core.Context):
	"""
	# The Transaction Context that manages the stack of protocols
	# used to facilitate arbitrary I/O streams.
	"""

	def actuate(self):
		pass

	def __init__(self):
		self._tp_channels = {}
		self._tp_stack = []

		self.tp_input = None
		self.tp_dispatch = None
		self.tp_output = None

	@classmethod
	def from_endpoint(Class, io, identifier='endpoint'):
		"""
		# Create and initialize an instance with the first transport layer.
		"""
		tp = Class()
		state, pair = io
		tp._tp_channels[(identifier, state)] = pair
		tp._tp_stack.append((identifier, state))
		return tp

	@classmethod
	def from_stack(Class, entries):
		"""
		# Create and initialize an instance with using a stack.
		"""
		tp = Class()
		return tp.tp_extend(entries)

	def xact_void(self, xact):
		self.tp_dispatch.terminate()
		self.terminate()

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

	def tp_connect(self, router, protocol,
			Dispatch=Invocations,
			Input=core.Transaction,
			Output=core.Transaction,
		):
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

		end.append(flows.Catenation())
		end.reverse()
		self.tp_output = o = Output.create(Transfer())
		self.xact_dispatch(o)
		o.xact_context.io_flow(end)

		self.tp_dispatch = inv = Dispatch(end[0], router)
		self.xact_dispatch(inv)

		start.append(flows.Division(inv))
		self.tp_input = i = Input.create(Transfer())
		self.xact_dispatch(i)
		i.xact_context.io_flow(start)
		self._pair = {i,o}

		return inv

	def tp_push(self, state, io):
		"""
		# Push the protocol channels on to the stack.
		"""

		self._tp_channels[state] = io
		top = self._tp_stack[-1]
		self._tp_stack.append(state)
		dispatch = self.sector.dispatch
		top[0].f_inject(io[0])
		top[1].f_inject(io[1])
		top[0].sector.dispatch(io[0])
		top[1].sector.dispatch(io[1])

	def tp_protocol_terminated(self, state):
		"""
		# Called by a protocol stack entry when both sides of the state have been closed.
		"""
		self.tp_dispatch.terminate()

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

	def io_execute(self):
		self.tp_input.xact_context.io_execute()

	def io_transmit_close(self):
		"""
		# Close the outgoing transfer context.
		"""
		self.tp_output.xact_context.io_terminate()

class Interface(core.Context):
	"""
	# Application context managing a logical interfaces.
	"""
	_if_initial = None

	def __init__(self, target, prepare):
		self.if_target = target
		self.if_prepare = prepare

	def actuate(self):
		if self._if_initial is not None:
			self._if_dispatch(self._if_initial)
			del self._if_initial

	def if_transition(self, ports, chain=itertools.chain.from_iterable):
		eps = map(self.system.allocate_transport, chain(ports))
		return self.if_target((self, self.if_prepare(self, eps)))

	def if_install(self, kports):
		"""
		# Given file descriptors, install a new set of flows
		# accepting sockets from the given listening sockets.
		"""

		if not self.functioning:
			if self._if_initial is None:
				self._if_initial = kports
			else:
				self._if_initial += kports
		else:
			self._if_dispatch(kports)

	def _if_dispatch(self, kports):
		acquire = self.system.acquire_listening_sockets
		create = core.Transaction.create
		dispatch = self.sector.dispatch
		fdispatch = flows.Dispatch

		for listen in acquire(kports):
			x, flow = listen

			t = Transfer()
			xact = create(t)
			dispatch(xact)
			t.io_flow([flow, fdispatch(self.if_transition)])
			flow.f_transfer(None)

	def xact_exit(self, transport):
		pass

	def xact_void(self, final):
		# Service Context; does not exit unless terminating.
		if self.terminating:
			self.finish_termination()

	@property
	def if_sockets(self):
		return self.sector.subtransactions

	def terminate(self):
		if not self.functioning:
			return

		self.start_termination()
		for xact in self.if_sockets:
			xact.terminate()

		self.xact_exit_if_empty()

class Connections(core.Context):
	"""
	# Application context managing accepted transports.
	"""

	def __init__(self, dispatch):
		self.cxn_dispatch = dispatch
		self.cxn_count = 0

	def cxn_accept(self, packet, chain=itertools.chain.from_iterable):
		"""
		# Moving to Sockets. Routing will be handled with flows.
		"""
		xdispatch = self.sector.dispatch
		idispatch = self.cxn_dispatch

		source, events = packet
		for endpoint, stack, protocol in events:
			tp = Transport.from_endpoint(endpoint)
			if stack:
				tp.tp_extend(stack)
			xact = core.Transaction.create(tp)
			xdispatch(xact)
			self.cxn_count += 1

			inv = tp.tp_connect(idispatch, protocol)
			endpoint[1][0].f_transfer(None)

	def xact_exit(self, transport):
		self.cxn_count -= 1

	def xact_void(self, final):
		# Service Context; does not exit unless terminating.
		if self.terminating:
			self.finish_termination()

	def terminate(self):
		if not self.functioning:
			return

		self.start_termination()
		self.xact_exit_if_empty()

def dispatch(xact, *flows:typing.Sequence[flows.Channel]):
	"""
	# Dispatch a set of a flows within the Transaction as connected Transfers.
	"""

	for x in reversed(flows):
		xf = Transfer()
		sub = xact.create(xf)
		xact.dispatch(sub)
		xf.critical(functools.partial(xf.io_flow, *x))
