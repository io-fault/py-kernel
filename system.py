"""
# Engine for running Processing Graphs on the local system.

# [ Properties ]

# /io_adapter/
	# The &Adapter instance used by &.system.Process to manage I/O events.
# /__process_index__/
	# Indirect association of &Proces and &Context
# /__io_index__/
	# Indirect association of Logical Process objects and traffic Interchanges.
	# Interchange holds references back to the process.
"""

import os
import sys
import functools
import collections
import contextlib
import inspect
import weakref
import queue
import traceback
import itertools
import typing
import signal # masking SIGINT/SIGTERM in threads.
import operator
import time

from ..context import tools

from ..system import kernel
from ..system import network
from ..system import io
from ..system import events
from ..system import process
from ..system import thread
from ..system import memory
from ..system import execution

from ..time import types as timetypes
from ..time import sysclock

from . import core
from . import flows
from . import text

__process_index__ = dict()
__io_index__ = dict()

# This class primarily exists for documentation purposes.
class Adapter(tuple):
	"""
	# A pair defining how transfers should be processed by a &Matrix.

	# Matrix Adapters convert Array Transfer Events into events suitable for processing by
	# the application.
	"""
	__slots__ = ()

	@property
	def endpoint(self):
		"""
		# The endpoint is a callable that receives the transformed transfers processed by
		# &transformer.
		"""
		return self[0]

	@property
	def transformer(self):
		"""
		# The transformer is a callable that processes a Array that is currently in a
		# cycle. The results are passed onto the &endpoint *after* the cycle exits.
		"""
		return self[1]

	@classmethod
	def create(Class, endpoint, transformer):
		r =  Class(endpoint, transformer)
		hash(r) # must be hashable
		return r

	def __new__(Class, endpoint, transformer):
		return tuple.__new__(Class, (endpoint, transformer))

def synchronize_io_events(arg, partial=functools.partial):
	"""
	# Send the event queue to the main task queue.
	# Enqueue's &deliver_io_events with the queue constructed by &separate_io_events.
	"""

	array, queue = arg
	if not queue:
		return # Nothing to do.

	# array.link is a &Process
	array.link.enqueue(partial(deliver_io_events, array, queue))

class Delta(tuple):
	"""
	# Tuple subclass holding a Channel transfer snapshot.

	# ! WARNING:
		# This class is not stable.
	"""
	__slots__ = ()

	def __str__(self):
		xfer = self[0]
		send = isinstance(xfer, int)
		s = {True: '↑ ', False: '↓ '}[send]

		if xfer is not None:
			s += 'transfer: ' + repr(bytes(xfer[:120]))

		if self.terminal:
			s += '..TERMINATED\n'
		else:
			if self.demand is not None:
				s += '...EXHAUSTED RESOURCE'
		return s

	def __repr__(self):
		return "{0}.{1}.construct(payload = {2!r}, demand = {3!r}, terminated = {4!r})".format(
			__name__, self.__class__.__name__, *self
		)

	@property
	def payload(self):
		"""
		# Units sent.
		"""
		return self[0]

	@property
	def demand(self):
		"""
		# The acquire method of the channel if exhausted. &None if not exhausted.
		"""
		return self[1]

	@property
	def terminal(self):
		"""
		# Whether or not this is the last event from the Channel.
		"""
		return self[2] is not None

	@property
	def endpoint(self):
		if self[2] is not None:
			return self[2][-1]
		return None

	@classmethod
	def construct(Class, payload = None, demand = None, terminated = None):
		return Class((payload, demand, terminated))

	@classmethod
	def snapshot(Class, channel):
		demand = None
		term = None

		if channel.terminated:
			# XXX: investigate cases where port can be None.
			p = channel.port
			if p is not None and p.error_code == 0:
				term = True
			else:
				term = (p, channel.endpoint())
		else:
			if channel.exhausted is True:
				demand = channel.acquire

		return Class((channel.transfer(), demand, term))

def separate_io_events(
		array,
		Queue=list,
		snapshot=Delta.snapshot,
		iter=iter,
		MemoryError=MemoryError,
		sleep=time.sleep,
	):
	"""
	# Process the array's transfer and construct a sequence of I/O events.

	# This is executed inside a thread managed by the interchange and *cannot* deliver
	# the events to Transformers. &synchronize_io_events is used to deliver the queue
	# for processing in the main task queue.
	"""

	# In a thread *outside* of the task queue, so is inappropriate
	# to run process() methods on transformers.
	# Build the transfer set for processing in the task queue.

	q = Queue()
	add = q.append
	i = iter(array.transfer())

	# currently this while loop is pointless
	# however, it is the frame that should house retry attempts in the face of memory errors.
	complete = False

	while not complete:
		try:
			for x in i:
				add((x.link, snapshot(x)))
			else:
				complete = True
		except MemoryError:
			# sleep and try again
			# THIS BLOCKS I/O FOR THE Array instance.
			while True:
				try:
					sleep(1)
					add((x.link, snapshot(x)))
					break
				except MemoryError:
					pass

	return (array, q)

io_adapter = Adapter(synchronize_io_events, separate_io_events)

class Matrix(object):
	"""
	# A partitioned set of IO Arrays.
	"""
	channels_per_array = 1024 * 32

	def __init__(self, adapter, execute=None):
		self.routes = {'system': io}
		self.adapter = adapter
		self.arrays = {}

		# execute is managed differently as the adapter *should not*
		# be written to depending on the method of thread execution.
		if execute is None:
			# default to a threading based instance,
			# but allow overrides
			import threading # only import threading if need be

			def execute(callable, *args, T = threading.Thread):
				t = T(target = callable, args = args)
				t.start()
				return t

		self._execute = execute

	def _setup(self, id=None, route='system'):
		# Create the Array instance and start its loop in a new thread.
		j = self.routes[route].Array()
		j.link = id
		self.arrays[id].add(j)
		t = self._execute(self._array_loop, id, j)
		return (t, j)

	def _get(self, id=None, route='system', get0=operator.itemgetter(0)):
		s = self.arrays.setdefault(id, set())
		# otherwise adapter by volume and return the "lowest"
		# XXX: This is a poor way to load balance arrays.
		r = ()
		while not r:
			r = sorted([(x.volume, x) for x in s if x.terminated == False], key = get0)
			if not r:
				self._setup(id = id)
			else:
				return r[0][1]

	def _iterarrays(self, chain=itertools.chain.from_iterable):
		return chain(self.arrays.values()) # get a snapshot.

	def __repr__(self):
		return "{1}.{0}()".format(self.__class__.__name__, __name__)

	def route(self, **routes):
		"""
		# Add a new implementation to the Matrix.
		"""
		self.routes.update(routes)

	def void(self):
		"""
		# Violently destroy all channels and Arrays in the Matrix.

		# All arrays allocated by the Matrix will be terminated.

		# ! WARNING:
			# This method should *only* be ran *after* forking and *inside the child process*.
		"""
		for x in self._iterarrays():
			x.void()
		self.arrays.clear()

	def terminate(self):
		"""
		# Terminate all arrays managed by the interchange.

		# This method should be ran during process termination where graceful shutdown is
		# desired.
		"""
		for x in list(self._iterarrays()):
			x.terminate()

	# Method ran in threads. The thread's existence is dependent on Array.terminated.
	def _array_loop(self, id, j, limit=16):
		# This loop runs the transformers and endpoint adapter callbacks until
		# the countdown reaches zero. If the countdown reaches zero and
		# there are no Channels in the Array, the array will terminate.
		# If there are Channels in the array, the countdown resets.

		# Cache the endpoint and the transformers.
		# This should already be setup by the user before allocating channels.
		Terminated = io.TransitionViolation
		ep, xf = self.adapter
		key = id
		localset = self.arrays[key]
		exit_at_zero = limit

		try:
			# A countdown is used to identify when to exit the thread without
			# explicit termination.
			# Automatic shutdown is a feature of Matrix to reduce unnecessary
			# resource usage.

			while not j.terminated:
				try:
					while exit_at_zero:
						# run an i/o cycle; if no events are there to be received, it will
						# block for a short time before falling through.
						with j:
							# run the adapter's transformer against the array returning
							# events that are suitable for the adapter's endpoint.
							events = xf(j)

						# run the adapter's endpoint.
						ep(events)

						# immediately delete events. It may be a while before it gets
						# replaced by the next cycle and we don't want to hold on to
						# those references for arbitrary periods of time.
						del events

						# Zero volume? Might be an unused array.
						if j.volume == 0:
							if j.terminated:
								# exotermination.
								exit_at_zero = 0
								if j in localset:
									localset.remove(j)
							else:
								# decrement count while the volume is zero.
								exit_at_zero -= 1

				except Terminated:
					pass

				# Empty.
				# Remove from set and restart countdown (lockless, so 2 phases)
				# Otherwise, terminate it.
				if j in localset:

					# This is how we avoid cases where termination is
					# triggered during a xact() that manages to refer to the
					# array we're considering termination on.
					localset.remove(j)

					# After the array is removed from the set, it's no longer
					# available for use by xact()'s. And while xact()'s can take
					# arbitrary amounts of time before a commit, this *would*
					# be a problem *if the commit did not* query for a array
					# at the end of the transaction.
					if not j.terminated:
						exit_at_zero = 3
					# Now, loop a couple more times to *reduce* the
					# probability of a race. In the rare case, we end up terminating
					# with channels in the array, so it's still important for the
					# user to perform retries.
				else:

					# Already removed from the visible set about 18 seconds ago.
					# Maybe a no-op given exotermination (Matrix.terminate())
					j.terminate()
		finally:
			# exiting. the array was terminated so this will be the final
			# cycle however, termination may have already been processed, so
			# this could raise the TerminatedError.

			try:
				# collect remaining transfers
				with j:
					# run the adapter's transformer against the array returning
					# events that are suitable for the adapter's endpoint.
					events = xf(j)

				# run the adapter's endpoint.
				ep(events)
				# immediately delete events. It may be a while before it gets
				# replaced by the next cycle and we don't want to hold on to
				# those references for arbitrary periods of time.
				del events
			except Terminated:
				#  covers a race case with termination.
				pass

			# remove the array from the localset if it hasn't been removed yet.
			if j in localset:
				localset.remove(j)

	def force(self, id=None):
		"""
		# Execute the Array.force method on the set designated
		# of Array instances designated by &id.

		# [ Parameters ]
		# /id/
			# The identifier for the set of Array instances.
		"""
		j = self.arrays.get(id, ())
		for x in j:
			x.force()

	def activity(self):
		"""
		# Signal the arrays that there was traffic activity that should be
		# attended to.

		# Must be after a set of resources have been acquired by Channels.
		"""
		for x in self._iterarrays():
			x.force()

	def acquire(self, id, channels, len=len):
		"""
		# Acquire a set of channels accounting for volume limits.
		"""
		array = self._get(id = id)

		nt = len(channels)
		nv = array.volume + nt # new volume
		overflow = nv - self.channels_per_array # count exceeding limit
		position = nt - overflow # transition point for new array

		ja = array.acquire
		for x in channels[:position]:
			ja(x) # array.acquire(channel)

		if overflow > 0:
			self._setup(id = id)

			array = self._get(id = id)
			ja = array.acquire

			for x in channels[position:]:
				ja(x) # array.acquire(channel)

# This is executed by the main task queue of a &Process instance.
# It ends up being a sub-queue for I/O events and has similar logic for managing
# exceptions.

def deliver_io_events(array, events, iter=iter):
	"""
	# Send the individual &events originally prepared by
	# &separate_io_events to their associated &KInput or &KOutput flows.
	"""

	complete = False
	ievents = iter(events)
	while not complete:
		kp = link = delta = flow = None
		try:
			for event in ievents:
				link, delta = event

				kp = link
				if kp is None:
					# Ignore event for None links.
					continue

				# *MUST* rely on exhaust events here. If we peek ahead of the
				# event callback, it may run a double acquire().
				xfer, demand, term = delta

				if xfer is not None:
					# send transfer regardless of termination
					# data may be transferred while the termination
					# condition is present, so its important it gets sent
					# prior to running the KernelPort's termination.
					kp.f_emit((xfer,))

				if demand is not None:
					kp.k_transition() # Accept the next memory transfer.

				if term and not (kp.terminated or kp.interrupted):
					kp.f_terminated()

				link = None
			else:
				complete = True # Done processing events.
		except BaseException as exception:
			try:
				if link is None:
					# failed to unpack the kp and delta from event
					# generally this shouldn't happen and usually refers
					# to a programming error.
					array.link.error((array, event), exception)
				else:
					kp.fault(exception)
			except BaseException as exc:
				# Record exception of cleanup failure.
				# TODO: Note as cleanup failure.
				array.link.error((array, event), exc)

class KChannel(flows.Channel):
	"""
	# Channel moving data in or out of the operating system's kernel.
	# The &KInput and &KOutput implementations providing for the necessary specializations.
	"""
	k_status = None

	def __init__(self, channel=None):
		self.channel = channel
		self.acquire = channel.acquire
		channel.link = self

	def actuate(self):
		self.system._io_attach(self.channel)

	def k_meta(self):
		if self.channel:
			return self.channel.port, self.channel.endpoint()
		else:
			return self.k_status

	def __repr__(self):
		c = self.__class__
		mn = c.__module__.rsplit('.', 1)[-1]
		qn = c.__qualname__
		port, ep = self.k_meta()

		if self.channel is None:
			res = "(no channel)"
		else:
			if self.channel.resource is None:
				res = "none"
			else:
				res = str(len(self.channel.resource))

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
		if self.channel is not None:
			r = self.channel.resource
			p.append(('resource', len(r) if r is not None else 'none'))

		return (p, ())

	def k_transition(self):
		# Called when the resource was exhausted
		# Unused atm and pending deletion.
		raise NotImplementedError("kernel flows must implement transition")

	def k_kill(self):
		"""
		# Called by the controlling &Flow, acquire status information and
		# unlink the channel.
		"""

		t = self.channel
		self.channel = None
		self.k_status = (t.port, t.endpoint())
		t.link = None # signals I/O loop to not inject.
		t.terminate() # terminates one direction.

		return t

	def interrupt(self):
		if self.channel is not None:
			self.k_kill()
		super().interrupt()

	def f_terminated(self):
		# THIS METHOD IS NOT CALLED IF F_TERMINATE/INTERRUPT() WAS USED.
		#assert not self.interrupted and not self.terminated

		# Called when the termination condition is received,
		# but *after* any transfers have been injected.

		# &.traffic calls this when it sees termination of the channel.

		if self.channel is None:
			# terminate has already been ran; status is *likely* present
			return

		self.k_kill()

		# No need to run channel.terminate() as this is only
		# executed by io.traffic in response to shutdown.

		# Exception is not thrown as the transport's error condition
		# might be irrelevant to the success of the application.
		# If a transaction was successfully committed and followed
		# with a transport error, it's probably appropriate to
		# show the transport issue, if any, as a warning.
		self._f_terminated()

	def f_transfer(self, event, source=None):
		raise NotImplementedError("must be provided by subclass")

	@property
	def k_transferring(self, len=len):
		"""
		# The length of the buffer being transferred into or out of the kernel.

		# &None if no transfer is currently taking place.
		"""
		x = self.channel
		if x is not None:
			x = x.resource
			if x is not None:
				return len(x)

		return None

class KAllocate(KChannel):
	"""
	# Flow that continually allocates memory for a channel transferring data into the process.
	"""

	ki_allocate, ki_resource_size = (None, None)

	def f_clear(self, obstruction):
		if super().f_clear(obstruction) and self.channel.resource is None:
			self.k_transition()

	def k_transition(self):
		"""
		# Transition in the next buffer provided that the Flow was not obstructed.
		"""

		if self.f_obstructed:
			# Don't allocate another buffer if the flow has been
			# explicitly obstructed by the downstream.
			return

		self.acquire(self.ki_allocate(self.ki_resource_size))

	def f_transfer(self, event, source=None):
		"""
		# Normally ignored, but will induce a transition if no transfer is occurring.
		"""

		if self.channel.resource is None:
			self.k_transition()

class KAccept(KAllocate):
	"""
	# Receive integer arrays from the system I/O channel.
	"""

	ki_allocate, ki_resource_size = (kernel.Ports.allocate, 24)

class KInput(KAllocate):
	"""
	# Receive octets from the system I/O channel.
	"""

	ki_allocate, ki_resource_size = (bytearray, 1024*4*2)

class KLimit(KInput):
	"""
	# Receive octets from the system I/O channel with limited memory allocations.
	# Primarily used to read portions of a file.
	"""
	k_limit = None

	def k_set_limit(self, limit, repeat=itertools.repeat, chain=itertools.chain):
		assert self.k_limit is None # Once.

		self.k_limit = limit
		allocsize = self.ki_resource_size

		buffers = limit // allocsize
		remainder = limit - (buffers * allocsize)
		initial = repeat(allocsize, buffers)

		self._k_limit_state = iter(chain(initial, (remainder,)))

		return self

	def k_transition(self):
		"""
		# Transition in the next buffer provided that the Flow was not obstructed.
		"""

		if self.f_obstructed:
			# Don't allocate another buffer if the flow has been
			# explicitly obstructed by the downstream.
			return

		for r_size in self._k_limit_state: # HINT: k_set_limit not called?
			self.acquire(self.ki_allocate(r_size))
			break
		else:
			self.channel.terminate()

class KOutput(KChannel):
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
			self.channel is not None and \
			len(self.ko_queue) == 0 and \
			self.channel.resource is None
		)

	def __init__(self, channel, Queue=collections.deque):
		super().__init__(channel=channel)
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
				# Termination set and no available event in queue?
				self.channel.terminate()
				self._f_terminated()

	def f_transfer(self, event, source=None, len=len):
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
					core.Condition(self, ('ko_overflow',))
				)

	def f_terminate(self):
		if self.terminating:
			return False

		# Flow-level Termination occurs when the queue is clear.
		self.start_termination()

		if self.f_empty:
			# Only terminate channel if it's empty.
			self.channel.terminate()
			self._f_terminated()

		# Note termination signalled.
		return True

class Context(core.Context):
	"""
	# System Context implementation for supplying Processing Graphs with access
	# to the local system.
	"""

	@property
	def scheduler(self):
		"""
		# The scheduler processor associated with the system context.
		"""
		only, = self.sector.processors[core.Scheduler]
		return only

	def xact_exit(self, xact:core.Transaction):
		ctx = xact.xact_context
		if ctx.exe_faults:
			sys.stderr.writelines(x+"\n" for x in text.format(ctx.exe_identifier, xact))
			sys.stderr.write("\n")
			sys.stderr.flush()
			for ident, procs in ctx.exe_faults.items():
				sys.stderr.writelines(x+"\n" for x in text.format(ident, procs))
				sys.stderr.write("\n")
				sys.stderr.flush()

	def xact_void(self, final:core.Transaction):
		"""
		# Final (executable) transaction exited; system process context complete.
		"""

		status = getattr(final.xact_context, 'exe_status', None)
		self.sector.interrupt()
		self.process.terminate(status)

	def interrupt(self):
		self._io_flush = tools.nothing
		self._io_attach = tools.nothing
		self._io_cycle = tools.nothing

	def terminate(self):
		self.start_termination()
		for x, xact in self.executables.items():
			xact.terminate()

	@property
	def process(self):
		return self._process_ref()

	def __init__(self, process):
		self._process_ref = weakref.ref(process)
		self.executables = weakref.WeakValueDictionary()
		self.attachments = []

	def structure(self):
		proc = self.process
		sr = ()

		p = [
			('tasks', proc.executed_task_count),
			('threads', len(proc.fabric.threading)),

			# Track basic (task loop) cycle stats.
			('cycles', proc.cycle_count),
		]

		return (p, sr)

	def actuate(self):
		# Allows the roots to perform scheduling.
		self.provide('system')
		assert self.sector.system is self

	def connect_process_exit(self, xact_context, callback, *processes):
		p = self.process
		k = p.kernel
		track = k.track
		event_connect = p.system_event_connect

		for pid in processes:
			try:
				track(pid)
			except:
				xact_context.critical(functools.partial(callback, pid))
			else:
				event_connect(('process', pid), xact_context, callback)

	def allocate(self, xactctx):
		"""
		# Launch an Executable for running application processors.
		"""
		xact = core.Transaction.create(xactctx)
		xact.executable = xactctx
		xact.system = self
		xactctx.system = self
		self.executables[xactctx.exe_identifier] = xact
		self.sector.dispatch(xact)

	def report(self, target):
		"""
		# Send an overview of the logical process state to the given target.
		"""

		target("\n".join(text.format('process-transaction', self.sector)))
		target("\n")

	def defer(self, measure, task, maximum=6000, seconds=timetypes.Measure.of(second=2)):
		"""
		# Schedule the task for execution after the period of time &measure elapses.

		# &.core.Scheduler instances will resubmit a task if there is a substantial delay
		# remaining. When large duration defers are placed, the seconds unit are used
		# and decidedly inexact, so resubmission is used with a finer grain.
		"""

		# select the granularity based on the measure

		if measure > seconds:
			# greater than two seconds
			quantity = min(measure.select('second'), maximum)
			quantity -= 1
			unit = 's'
		elif measure < 10000:
			# measures are in nanoseconds
			unit = 'n'
			quantity = measure
		elif measure < 1000000:
			unit = 'u'
			quantity = measure.select('microsecond')
		else:
			unit = 'm'
			quantity = min(measure.select('millisecond'), 0xFFFFFFFF)

		return self.process.kernel.alarm(task, quantity, unit)

	def cancel(self, task):
		"""
		# Cancel a scheduled task.
		"""

		return self.process.kernel.cancel(task)

	def inherit(self, context):
		"""
		# Inherit the exports from the given &context.
		"""

		raise Exception("not implemented")

	def _io_cycle(self):
		"""
		# Signal the &Process that I/O occurred for this context.
		"""

		self.process.iomatrix.force(id=self)

	# Primary access to processor resources: task queue, work thread, and threads.
	def _io_attach(self, *channels):
		# Enqueue flush once to clear new channels.
		if not self.attachments:
			self.enqueue(self._io_flush)
		self.attachments.extend(channels)

	def _io_flush(self):
		# Needs main task queue context.
		new_channels = self.attachments
		self.attachments = []

		ix = self.process.iomatrix
		ix.acquire(self, new_channels)
		ix.force(id=self)
		del ix

	def execute(self, controller, function, *parameters):
		"""
		# Execute the given function in a thread associated with the specified controller.
		"""

		return self.process.fabric.execute(controller, function, *parameters)

	def environ(self, identifier, default=None):
		"""
		# Access the environment from the perspective of the context.
		# Context overrides may hide process environment variables.
		"""

		if identifier in self.environment:
			return self.environment[identifier]

		return os.environ.get(identifier, default)

	def override(self, identifier, value):
		"""
		# Override an environment variable for the execution context.

		# Child processes spawned relative to the context will inherit the overrides.
		"""

		if self.environment:
			self.environment[identifier] = value
		else:
			self.environment = {}
			self.environment[identifier] = value

	def bindings(self, *allocs):
		"""
		# Returns a sequence of file descriptors that can later be acquired by a Matrix.
		"""

		for endpoint in allocs:
			yield network.service(endpoint)

	def connect(self, endpoint):
		"""
		# Given an endpoint and a transport stack, return the series used to
		# manage the connection's I/O.

		# [ Parameters ]

		# /endpoint/
			# The &.library.Endpoint instance describing the target of the connection.
		"""

		i, o = io.alloc_octets(network.connect(endpoint))
		return (('socket', o.port), (KInput(i), KOutput(o)))

	def allocate_transport(self, fd):
		"""
		# Given a file descriptor and a transport stack, return the series used to
		# manage the connection's I/O.

		# [ Parameters ]
		# /fd/
			# Socket file descriptor.
		"""

		i, o = io.alloc_octets(fd)
		return i.port, (KInput(i), KOutput(o))

	def read_file(self, path):
		"""
		# Construct a channel for reading an entire file from the filesystem.
		# The returned channel terminates when EOF occurs; often,
		# &read_file_range is preferrable to avoid status inconsistencies.
		"""

		fd = os.open(path, os.O_RDONLY)
		return KInput(io.alloc_input(fd))

	def read_file_range(self, path, start, stop,
			open=os.open, seek=os.lseek, close=os.close,
		):
		"""
		# Construct a channel to read a specific range of a file.
		"""

		size = stop - start
		if size < 0:
			raise ValueError("start exceeds stop")

		fd = open(path, os.O_RDONLY)

		try:
			if start:
				seek(fd, start, 0)

			return KLimit(io.alloc_input(fd)).k_set_limit(size)
		except:
			close(fd)
			raise

	def append_file(self, path):
		"""
		# Open a set of files for appending through a &.library.KernelPort.
		"""

		fd = os.open(path, os.O_WRONLY|os.O_APPEND|os.O_CREAT)
		return KOutput(io.alloc_output(fd))

	def update_file(self, path, offset, size):
		"""
		# Allocate a channel for overwriting data at the given offset of
		# the designated file.
		"""

		fd = os.open(path, os.O_WRONLY|os.O_APPEND|os.O_CREAT)
		position = os.lseek(fd, 0, offset)
		t = io.alloc_output(fd)

		return KOutput(t)

	def listen(self, interfaces):
		"""
		# On POSIX systems, this performs (system/manual)`bind` *and*
		# (system/manual)`listen` system calls for receiving socket connections.

		# Returns a generator producing (interface, KAccept) pairs.
		"""

		for x in interfaces:
			t = io.alloc_service(network.service(x))
			yield (x, KAccept(t))

	def acquire_listening_sockets(self, kports):
		"""
		# Acquire the channels necessary for the set of &kports, file descriptors,
		# and construct a pair of &KernelPort instances to represent them inside a &Flow.

		# [ Parameters ]

		# /kports/
			# An iterable consisting of file descriptors referring to sockets.

		# [ Returns ]

		# /&Type/
			# Iterable of pairs. First item of each pair being the interface's local endpoint,
			# and the second being the &KernelPort instance.
		"""

		for kp in kports:
			socket_channel = io.alloc_service(kp)
			yield (socket_channel.endpoint(), KAccept(socket_channel))

	def connect_output(self, fd):
		"""
		# Allocate channel instances for the given sequence
		# of file descriptors.
		"""

		return KOutput(io.alloc_output(fd))

	def connect_input(self, fd):
		"""
		# Allocate channel instances for the given sequence
		# of file descriptors.
		"""

		return KInput(io.alloc_input(fd))

	def daemon(self, invocation, close=os.close) -> typing.Tuple[int, int]:
		"""
		# Execute the &..system.execution.KInvocation instance with stdin and stdout closed.

		# Returns the process identifier and standard error's file descriptor as a tuple.
		"""

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
		except:
			close(stderr[0])
			raise

		return pid, stderr[0]

	def daemon_stderr(self, stderr, invocation, close=os.close):
		"""
		# Execute the &..system.execution.KInvocation instance with stdin and stdout closed.
		# The &stderr parameter will be passed in as the standard error file descriptor,
		# and then *closed* before returning.

		# Returns a &Subprocess instance containing a single Process-Id.

		# Used to launch a daemon with a specific standard error for monitoring purposes.
		"""

		stdout = stdin = ()

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

		return pid

	def system_execute(self, invocation:execution.KInvocation):
		"""
		# Execute the &..system.execution.KInvocation inheriting standard input, output, and error.

		# This is used almost exclusively by shell-type processes where the calling process
		# suspends TTY I/O until the child exits.
		"""

		return Subprocess(invocation())

	def stream_shared_segments(self, path:str, range:tuple, *_, Segments=memory.Segments):
		"""
		# Construct a new Flow with an initial Iterate Transformer
		# flowing shared memory segments from the memory mapped file.

		# Returns a pair, the new Flow and a callable that causes the Flow to begin
		# transferring memory segments.

		# [ Parameters ]
		# /path/
			# Local filesystem path to read from.
		# /range/
			# A triple, (start, stop, size), or &None if the entire file should be used.
			# Where size is the size of the memory slices to emit.
		"""

		segs = Segments.open(path)
		return flows.Iteration((x,) for x in segs)

	def coprocess(self, identifier, exit, invocation, application):
		"""
		# Dispatch a local parallel process.
		"""
		return dispatch(invocation, application, identifier, exit=exit)

class Fabric(object):
	"""
	# Thread manager for processes; thread pool with capacity to manage dedicated threads.
	"""

	def __init__(self, process, proxy=weakref.proxy):
		self.process = proxy(process) # report unhandled thread exceptions
		self.threading = dict() # dedicated purpose threads

	def void(self):
		"""
		# Normally used after a process fork in the child.
		"""

		self.threading.clear()

	def execute(self, controller, callable, *args):
		"""
		# Create a dedicated thread and execute the given callable within it.
		"""

		self.spawn(weakref.ref(controller), callable, args)

	def critical(self, controller, context, callable, *args):
		"""
		# Create a dedicated thread that is identified as a critical resource where exceptions
		# trigger &process.Panic exceptions in the main thread.

		# The additional &context parameter is an arbitrary object describing the resource;
		# often the object whose method is considered critical.
		"""

		self.spawn(weakref.ref(controller), process.critical, (context, callable) + args)

	def spawn(self, controller, callable, args, create_thread=thread.create):
		"""
		# Add a thread to the fabric.
		# This expands the "parallel" capacity of a &Process.
		"""

		tid = create_thread(self.thread, (controller, (callable, args)))
		return tid

	def thread(self, *parameters, gettid=thread.identify):
		"""
		# Manage the execution of a thread.
		"""

		# Block INT and TERM from fabric threads.
		# Necessary to allow process.protect()'s sleep function to
		# be interrupted when a signal is received.
		signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT, signal.SIGTERM})

		controller, thread_root = parameters
		tid = gettid()

		try:
			try:
				self.threading[tid] = parameters

				thread_call, thread_args = thread_root
				del thread_root

				return thread_call(*thread_args)
			finally:
				del self.threading[tid]
		except BaseException as exception:
			self.process.error(controller, exception, "Thread")

	def executing(self, tid):
		"""
		# Whether or not the given thread [identifier] is executing in this Fabric instance.
		"""

		return tid in self.threading

class Process(object):
	"""
	# The representation of the system process that is running. Usually referred
	# to as `process` by &Context and other classes.

	# Usually only one &Process is active per-process, but it can be reasonable to launch multiple
	# in order to perform operations that would otherwise expect its own space.

	# [ System Events ]

	# The &system_event_connect and &system_event_disconnect methods
	# are the mechanisms used to respond to child process exits signals.

	# [ Properties ]

	# /fabric/
		# The &Fabric instance managing the threads controlled by the process.
	"""

	@staticmethod
	def current(tid=thread.identify):
		"""
		# Resolve the current logical process based on the thread's identifier.
		# &None is returned if the thread was not created by a &Process.
		"""

		x = tid()
		for y in __process_index__:
			if y.fabric.executing(x):
				return y

	def transaction(self) -> core.Transaction:
		"""
		# Return the primary &.library.Unit instance associated with the process.
		"""

		return __process_index__[self][0]

	def task_queue_reference(self):
		"""
		# Return the weak reference to &enqueue.
		"""
		bmethod = __process_index__[self][1]
		return weakref.proxy(bmethod)

	@property
	def iomatrix(self):
		"""
		# The &Matrix instance managing the I/O file descriptors used
		# by the &Process.
		"""
		return __io_index__[self]

	def actuate_root_transaction(self):
		xact = self.transaction()
		tqr = self.task_queue_reference()
		xact.enqueue = tqr
		xact._pexe_contexts = ('enqueue',)
		xact.actuate()
		core.set_actuated(xact)

	def log(self, data):
		"""
		# Append only access to a *critical* process log. Usually points to &sys.stderr and
		# primarily used for process related issues.
		"""

		self._logfile.write(data)
		self._logfile.flush()

	def boot(self, *tasks):
		"""
		# Boot the Process with the given tasks enqueued in the Task queue.

		# Only used inside the main thread for the initialization of the
		# controlling processor.
		"""

		process.fork_child_cleanup.add(self.void)

		self.kernel.enqueue(*[functools.partial(process.critical, None, x) for x in tasks])
		self.fabric.spawn(None, self.main, ()) # Main task queue thread.

		return self

	def terminate(self, status=None):
		"""
		# Terminate the process closing the task queue and running the invocation's exit.
		"""
		self._exit_stack.__exit__(None, None, None)

		del __process_index__[self]
		del __io_index__[self]

		if self.kernel is not None:
			self.kernel.enqueue(functools.partial(self._exit_cb, status))
			self.kernel.close()
		else:
			self._exit_cb(status)

	def __init__(self, exit, identifier):
		"""
		# Initialize the Process instance using the designated &identifier.
		# The identifier is essentially arbitrary, but must be hashable as it's
		# used to distinguish one &Representation from another. However,
		# usually there is only one process, so "root" or "main" is often used.

		# Normally, &execute is used to manage the construction of the
		# &Process instance.
		"""

		self._exit_cb = exit
		self.identifier = identifier

		self._init_kernel()
		self.enqueue = self.kernel.enqueue

		# track number of loops
		self.cycle_count = 0 # count of task cycles
		self.executed_task_count = 0
		self.cycle_start_time = None
		self.cycle_start_time_decay = None

		self._logfile = sys.stderr

		self._init_exit()
		self._init_fabric()
		self._init_system_events()
		self._init_io()

	def _init_kernel(self):
		self.kernel = events.Interface()

	def _init_exit(self):
		self._exit_stack = contextlib.ExitStack()
		self._exit_stack.__enter__()

	def _init_system_events(self):
		self.system_event_connections = {}
		self.system_event_connect(('signal', 'terminal.query'), None, self.report)

	def _init_fabric(self):
		self.fabric = Fabric(self)

	def _init_io(self, Matrix=Matrix):
		execute = functools.partial(self.fabric.critical, self, io_adapter)
		ix = Matrix(io_adapter, execute = execute)
		__io_index__[self] = ix

	def void(self):
		"""
		# Tear down the existing logical process state. Usually used internally after a
		# physical process fork.
		"""

		# Pending tasks will be discarded during dealloc.
		self.kernel.close()
		self.kernel = None
		self._init_kernel()

		# normally called in fork
		self._init_exit()
		self._init_fabric()
		self._init_system_events()

		self.iomatrix.void()

	def report(self):
		"""
		# Report a snapshot of the process' state to the given &target.
		"""

		self.log("[%s]\n" %(sysclock.now().select('iso'),))
		xact = __process_index__[self][0]
		xact.xact_context.report(self.log)

	def __repr__(self):
		return "{0}(identifier = {1!r})".format(self.__class__.__name__, self.identifier)

	def error(self, context, exception, title="Unspecified Execution Area"):
		"""
		# Handler for untrapped exceptions.
		"""

		exc = exception
		formatting = traceback.format_exception(exc.__class__, exc, exc.__traceback__)
		formatting = ''.join(formatting)

		self.log("[!#: ERROR: exception raised from %s: %r]\n%s" %(title, context, formatting))

	def main(self):
		"""
		# The main task loop executed by a dedicated thread created by &boot.
		"""

		try:
			self.loop()

			if self.kernel.loaded:
				# Clear queue and warn if not empty after this.
				self.kernel.execute(self.error)
				self.kernel.execute(self.error)
		except BaseException as critical_loop_exception:
			self.error(self.loop, critical_loop_exception, title="Process Task Queue Caller")

	def loop(self, partial=functools.partial, BaseException=BaseException):
		"""
		# Internal loop that processes the task queue. Executed by &boot in a thread
		# managed by &fabric.
		"""

		time_snapshot = sysclock.now
		ix = self.iomatrix
		io = ix.activity
		k = self.kernel
		sec = self.system_event_connections

		errctl = (lambda c,v: self.error(c, v, title='Task',))

		while not k.closed:
			self.cycle_count += 1
			self.cycle_start_time = time_snapshot()
			self.cycle_start_time_decay = 1 # Incremented by main thread.

			self.executed_task_count += k.execute(errctl)

			# This appears undesirable, but the alternative
			# is to run force for each process local I/O event.
			# Presuming that some I/O has occurred while processing
			# the queue is not terribly inaccurate.
			io()

			events = k.wait()

			# process unix signals and child exit events
			for event in events:
				remove_entry = False

				if event[0] == 'process':
					# Defer read until system event connect.
					# Might allow SIGCHLD support on linux.
					event = ('process', event[1])
					#args = (event[1], execution.reap(event[1]),)
					args = (event[1],)
					remove_entry = True
				elif event[0] == 'alarm':
					k.enqueue(event[1])
					continue
				else:
					args = ()

				if event in sec:
					callback = sec[event][1] # system_event_connections
					if remove_entry:
						# process events only occur once
						del sec[event]

					k.enqueue(partial(callback, *args))

			# for event
		# while True

	def system_event_connect(self, event, resource, callback):
		"""
		# Connect the given callback to system event, &event.
		# System events are given string identifiers.
		"""

		self.system_event_connections[event] = (resource, callback)

	def system_event_disconnect(self, event):
		"""
		# Disconnect the given callback from the system event.
		"""

		if event not in self.system_event_connections:
			return False

		del self.system_event_connections[event]
		return True

main_thread_task_queue = None
main_thread_interrupt = None
main_thread_exit_status = 255

def reset():
	"""
	# Reset the process global state of &.system.
	"""
	global main_thread_task_queue
	global main_thread_interrupt
	global main_thread_exit_status

	main_thread_task_queue = None
	main_thread_interrupt = None
	main_thread_exit_status = 255

def exit(status:int=None):
	"""
	# Default exit callback used to interrupt main thead task queue.

	# Sets the module attribute &main_thread_exit_status to the given status and closes the main task queue.
	"""
	global main_thread_exit_status

	if status is not None:
		main_thread_exit_status = status

	main_thread_task_queue.enqueue(main_thread_task_queue.close)

def spawn(exit, identifier, executables, critical=process.critical, partial=functools.partial) -> Process:
	"""
	# Construct a &Process using the given &executables.
	# The &identifier is usually `'root'` for the primary logical process.
	"""

	process = Process(exit, identifier)
	system = Context(process)
	xact = core.Transaction.create(system)
	enqueue = process.enqueue
	__process_index__[process] = (xact, enqueue)
	process.enqueue(partial(critical, None, process.actuate_root_transaction))

	for x in executables:
		process.enqueue(partial(system.allocate, x))

	return process

def dispatch(invocation, application:core.Context, identifier=None, exit=exit) -> Process:
	"""
	# Dispatch an application context instance within a new logical process.

	# Construct a &Process and &core.Executable for executing the &application context.
	# The &Process created by the inner &spawn is returned.
	"""

	aclass = type(application)
	exe = core.Executable(invocation, aclass.__name__)
	exe.exe_enqueue(application)
	process = spawn(exit, identifier, [exe])
	process.boot(exe.exe_initialize)

	return process

def set_root_process(process):
	"""
	# Connect the system process termination signal to root transaction terminate.
	"""
	from ..system import kernel
	xact, enqueue = __process_index__[process]

	callterm = functools.partial(enqueue, xact.terminate)
	def termsignal(signo, frame=None, setstatus=kernel.exit_by_signal):
		setstatus(signal.SIGTERM)
		callterm()

	signal.signal(signal.SIGTERM, termsignal)

def default_error_trap(call, error):
	global main_thread_interrupt

	import traceback

	if isinstance(error, process.ControlException):
		# Handles interjection based panics that run within
		# the main thread task queue.
		main_thread_interrupt = error
		process_exit(-1)
	else:
		traceback.print_exception(error.__class__, error, error.__traceback__)

def control(errctl=default_error_trap, **kw):
	"""
	# Control the main thread providing a low precision timer for deferred tasks.
	# Called by an application's main entry point after booting the &Process created
	# by &spawn.
	"""
	global main_thread_task_queue

	main_thread_task_queue = events.Interface()
	process.Fork.substitute(protect, errctl, **kw)

def protect(error_control, timeout=8):
	global main_thread_task_queue

	try:
		k = main_thread_task_queue

		while not k.closed:
			k.execute(error_control)
			k.wait(timeout)

		if main_thread_interrupt is None:
			k.execute(default_error_trap)
	finally:
		main_thread_task_queue = None

	if main_thread_exit_status >= 0:
		raise process.Exit(main_thread_exit_status)
	else:
		raise main_thread_interrupt or process.Panic("negative exit status set without exception")
