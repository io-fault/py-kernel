"""
# Process management classes.

# Implements the thread management and process representation management necessary
# to work with a set of &.library.Unit instances. &Context instances are indirectly
# associated with the &.library.Unit instances in order to allow &.library.Processor
# instances to cache access to &Context.enqueue.

# [ Properties ]

# /allocate/
	# Access to &..system.io.Array.rallocate for Channel allocations.
# /io_adapter/
	# The &Adapter instance used by &.system.Process to manage I/O events.
# /__process_index__/
	# Indirect association of &Proces and &Context
# /__traffic_index__/
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

from ..system import io
from ..system import events
from ..system import process
from ..system import thread
from ..system import memory
from ..system import execution

from ..time import library as libtime

__process_index__ = dict()
__traffic_index__ = dict()

allocate = io.Array.rallocate

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

	# array.link is a io.process.Representation()
	array.link.context.enqueue(partial(deliver_io_events, array, queue))

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

	# primary functionality of the callable yielded by the Matrix.xact() CM.
	def _alloc(self, id, target_set, *request, **kw):
		s = target_set[0]
		# This array must *not* be used to acquire.
		j = self._get(id = id)

		t = j.rallocate(*request, **kw)
		if isinstance(t, tuple):
			# need to be grouped up as
			# we want sockets to be acquired
			# by the same channel.
			s.add(t)
		else:
			s.add((t,))
		return t

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

	@contextlib.contextmanager
	def xact(self, id=None, route:str='system',
			partial=functools.partial,
			chain=itertools.chain.from_iterable
		):
		"""
		# A context manager yielding an object that can be called to allocate Channels for
		# use with the designated adapter. The Channels returned are automatically acquired
		# by the corresponding Array *when the context manager exits*.

		# The &id parameter selects the "bucket" that the allocated Channels belong
		# to--buckets being internally managed. This allows for explicit separation of allocated
		# Channels in order to prioritize certain Transits.

		# [ Parameters ]

		# /id/
			# Arbitrary identifier selecting the Channel "bucket".
		# /route/
			# Implementation identifier that selects the Array class to be used.
		"""
		tset = set()
		container = [tset]
		try:
			yield partial(self._alloc, id, container)

			# It is **critical** that we retrieve arrays here
			# as opposed to caching the list at rallocate() time.
			#
			# Array threads exist so long as the array is not terminated,
			# and arrays will terminate after a certain period if they
			# go unused. In order to operate in a lock free manner, we
			# remove the Array from the set inside the thread before
			# terminating it. This gives the thread a window in which they
			# can safely terminate the array without the fear of a race condition.

			self.acquire(id, list(chain(tset)))
		except:
			# shatter ports
			for channel in chain(tset):
				channel.port.shatter() # idempotent
				channel.terminate()
			raise

		finally:
			# Cause NameError's if alloc_and_acquire is called past exit.
			del container[:]

# This is executed by the main io.library task queue of a .process.Representation  instance.
# It ends up being a sub-queue for I/O events and has similar logic for managing
# exceptions.

def deliver_io_events(array, events, iter=iter):
	"""
	# Send the individual &events originally prepared by
	# &separate_io_events to their associated &.library.KInput or &.library.KOutput flows.
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

				if term:
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
				array.link.context.process.error((array, event), exc)

class Context(object):
	"""
	# Execution context class providing access to per-context resource acquisition.

	# Manages allocation of kernel provided resources, system command execution, threading,
	# I/O connections.

	# Contexts are the view to the &Process and the Kernel of the system running
	# the process. Subcontexts can be created to override the default functionality
	# and provide a different environment.

	# Contexts are associated with every &.library.Resource.
	"""

	inheritance = ('environment',)

	def __init__(self, process, *api):
		"""
		# Initialize a &Context instance with the given &process.
		"""

		self.process = process
		self.context = process
		self.association = None
		self.environment = ()
		self.attachments = [] # io channels to be acquired by an array

		self._connect, self._input, self._output, self._listen = api

	def associate(self, resource, Ref=weakref.ref):
		"""
		# Associate the context with a particular &.library.Resource object, &resource.

		# Only one association may exist and implies that the context will be destroyed
		# after the object is deleted.

		# Generally used by &.library.Sector instances that are augmenting the execution
		# context for subprocessors.
		"""

		self.association = Ref(resource)

	@property
	def unit(self):
		"""
		# The &Unit of the association.
		"""
		global Unit

		point = self.association()
		while point.controller is not None:
			point = point.controller

		return point

	def faulted(self, resource):
		"""
		# Notify the controlling &Unit instance of the fault.
		"""

		return self.unit.faulted(resource)

	def defer(self, measure, task, maximum=6000, seconds=libtime.Measure.of(second=2)):
		"""
		# Schedule the task for execution after the period of time &measure elapses.

		# &.library.Scheduler instances will resubmit a task if there is a substantial delay
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

	def _sys_traffic_cycle(self):
		"""
		# Signal the &Process that I/O occurred for this context.
		"""

		self.process.iomatrix.force(id=self.association())

	# Primary access to processor resources: task queue, work thread, and threads.
	def _sys_traffic_attach(self, *channels):
		# Enqueue flush once to clear new channels.
		if not self.attachments:
			self.enqueue(self._sys_traffic_flush)
		self.attachments.extend(channels)

	def _sys_traffic_flush(self):
		# Needs main task queue context.
		new_channels = self.attachments
		self.attachments = []

		unit = self.association()
		ix = self.process.iomatrix
		ix.acquire(unit, new_channels)
		ix.force(id=unit)

		del unit

	def interfaces(self, processor):
		"""
		# Iterator producing the stack of &Interface instances associated
		# with the sector ancestry.
		"""
		sector_scan = processor.controller
		while not isinstance(sector_scan, Unit):
			if isinstance(sector_scan, Sector):
				yield from sector_scan.processors.get(Interface, ())
			sector_scan = sector_scan.controller

	def enqueue(self, *tasks):
		"""
		# Enqueue the tasks for subsequent processing; used by threads to synchronize their effect.
		"""

		self.process.enqueue(*tasks)

	def execute(self, controller, function, *parameters):
		"""
		# Execute the given function in a thread associated with the specified controller.
		"""

		return self.process.fabric.execute(controller, function, *parameters)

	def environ(self, identifier):
		"""
		# Access the environment from the perspective of the context.
		# Context overrides may hide process environment variables.
		"""

		if identifier in self.environment:
			return self.environment[identifier]

		return os.environ.get(identifier)

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

	def bindings(self, *allocs, transmission = 'sockets'):
		"""
		# Allocate leaked listening interfaces.

		# Returns a sequence of file descriptors that can later be acquired by a Matrix.
		"""

		alloc = allocate
		unit = self.association()
		if unit is None:
			raise RuntimeError("context has no associated resource")

		# io normally works with channels that are attached to
		# an array, but in cases where it was never acquired, the
		# management operations still work.
		for endpoint in allocs:
			typ = endpoint.protocol
			t = alloc((transmission, typ), (str(endpoint.address), endpoint.port))

			fd = t.port.fileno
			t.port.leak()
			t.terminate()
			del t

			yield fd

	def connect_subflows_using(self, interface, endpoint, mitre, *protocols):
		"""
		# Given an endpoint and a transport stack, return the series used to
		# manage the connection's I/O from the given &interface.

		# [ Parameters ]

		# /interface/
			# The &.library.Endpoint instance describing the interface to use for the
			# connection.

		# /endpoint/
			# The &.library.Endpoint instance describing the target of the connection.

		# /protocols/
			# A sequence of transport layers to use with the &.library.Transport instances.
			# A &.library.Transport pair will be created even if &protocols is empty.
			# This parameter might be merged into the mitre.
		"""

		channels = allocate(
			('octets', endpoint.protocol), (str(endpoint.address), endpoint.port)
			# XXX: interface ref
		)
		return self._connect(mitre, channels, *protocols)

	def connect_subflows(self, endpoint, mitre, *protocols):
		"""
		# Given an endpoint and a transport stack, return the series used to
		# manage the connection's I/O.

		# [ Parameters ]

		# /endpoint/
			# The &.library.Endpoint instance describing the target of the connection.

		# /protocols/
			# A sequence of transport layers to use with the &.library.Transport instances.
			# A &.library.Transport pair will be created even if &protocols is empty.
			# This parameter might be merged into the mitre.
		"""

		channels = allocate(('octets', endpoint.protocol), (str(endpoint.address), endpoint.port))
		return self._connect(mitre, channels, *protocols)

	def accept_subflows(self, fd, mitre, *protocols):
		"""
		# Given a file descriptor and a transport stack, return the series used to
		# manage the connection's I/O.

		# [ Parameters ]
		# /fd/
			# The &.library.Endpoint instance describing the target of the connection.
		# /protocols/
			# A sequence of transport layers to use with the &.library.Transport instances.
			# A &.library.Transport pair will be created even if &protocols is empty.
			# This parameter might be merged into the mitre.
		"""

		channels = allocate('octets://acquire/socket', fd)
		return self._connect(mitre, channels, *protocols)

	def read_file(self, path):
		"""
		# Open a set of files for reading through a &.library.KernelPort.
		"""

		return self._input(allocate('octets://file/read', path))

	def append_file(self, path):
		"""
		# Open a set of files for appending through a &.library.KernelPort.
		"""

		return self._output(allocate('octets://file/append', path))

	def update_file(self, path, offset, size):
		"""
		# Allocate a transit for overwriting data at the given offset of
		# the designated file.
		"""

		t = allocate(('octets', 'file', 'overwrite'), path)
		position = os.lseek(t.port.fileno, 0, offset)

		return self._output(t)

	def listen(self, interfaces):
		"""
		# On POSIX systems, this performs (system:manual)`bind` *and*
		# (system/manual)`listen` system calls for receiving socket connections.

		# Returns a generator producing (interface, Flow) pairs.
		"""

		alloc = allocate

		for x in interfaces:
			t = alloc(('sockets', x.protocol), (str(x.address), x.port))
			yield (x, self._listen(t))

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

		alloc = allocate

		for kp in kports:
			socket_transit = alloc('sockets://acquire', kp)
			yield (socket_transit.endpoint(), self._listen(socket_transit))

	def connect_output(self, fd):
		"""
		# Allocate channel instances for the given sequence
		# of file descriptors.
		"""

		return self._output(allocate('octets://acquire/output', fd))

	def connect_input(self, fd):
		"""
		# Allocate channel instances for the given sequence
		# of file descriptors.
		"""

		return self._input(allocate('octets://acquire/input', fd))

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
		global Iteration, Flow

		segs = Segments.open(path, range)
		return Iteration(segs)

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
		global signal

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

	def primary(self) -> bool:
		"""
		# Return the primary &.library.Unit instance associated with the process.
		"""

		return __process_index__[self][None]

	@property
	def iomatrix(self):
		"""
		# The &Matrix instance managing the I/O file descriptors used
		# by the &Process.
		"""
		return __traffic_index__[self]

	@classmethod
	def spawn(Class, invocation, Unit, units, identity='root', critical=process.critical):
		"""
		# Construct a booted &Process using the given &invocation
		# with the specified &Unit.
		"""

		proc = Class(identity, invocation = invocation)
		lpd = {}
		__process_index__[proc] = lpd

		inits = []
		for identity, roots in units.items():
			unit = Unit()
			unit.requisite(identity, roots, process = proc, Context = Context)
			lpd[identity] = unit
			proc._enqueue(functools.partial(critical, None, unit.actuate))

		lpd[None] = unit # determines primary program
		return proc

	def log(self, data):
		"""
		# Append only access to a *critical* process log. Usually points to &sys.stderr and
		# primarily used for process related issues. Normally inappropriate for &Unit
		# instances.
		"""

		self._logfile.write(data)
		self._logfile.flush()

	def fork(self, *tasks):
		"""
		# Fork the process and enqueue the given tasks in the child.
		# Returns a &.library.Subprocess instance referring to the Process-Id.
		"""

		return process.Fork.dispatch(self.boot, *tasks)

	def actuate(self, *tasks):
		# kernel interface: watch process exits, process signals, and timers.
		self.kernel = events.Interface()
		self.enqueue(*[functools.partial(process.critical, None, x) for x in tasks])
		self.fabric.spawn(None, self.main, ())

	def boot(self, main_thread_calls, *tasks):
		"""
		# Boot the Process with the given tasks enqueued in the Task queue.

		# Only used inside the main thread for the initialization of the
		# controlling processor.
		"""
		global process

		if self.kernel is not None:
			raise RuntimeError("already booted")

		process.fork_child_cleanup.add(self.void)
		for boot_init_call in main_thread_calls:
			boot_init_call()

		self.actuate(*tasks)
		# replace boot() with protect() for main thread protection/watchdog
		process.Fork.substitute(process.protect)

	def main(self):
		"""
		# The main task loop executed by a dedicated thread created by &boot.
		"""

		# Normally
		try:
			self.loop()
		except BaseException as critical_loop_exception:
			self.error(self.loop, critical_loop_exception, title = "Task Loop")
			raise
			raise process.Panic("exception escaped process loop") # programming error in Process.loop

	def terminate(self, exit=None):
		"""
		# Terminate the Process. If no contexts remain, exit the process.
		"""
		self._exit_stack.__exit__(None, None, None)

		del __process_index__[self]
		del __traffic_index__[self]

		if not __process_index__:
			if exit is None:
				# no exit provided, so use our own exit code
				process.interject(process.Exit(250).raised)
			else:
				return self.invocation.exit(exit)

	def __init__(self, identity, invocation=None):
		"""
		# Initialize the Process instance using the designated &identity.
		# The identity is essentially arbitrary, but must be hashable as it's
		# used to distinguish one &Representation from another. However,
		# usually there is only one process, so "root" or "main" is often used.

		# Normally, &execute is used to manage the construction of the
		# &Process instance.
		"""

		# Context Wide Resources
		self.identity = identity
		self.invocation = invocation # exit resource and invocation parameters

		# track number of loop and designate maintenance frequency
		self.cycle_count = 0 # count of task cycles
		self.cycle_start_time = None
		self.cycle_start_time_decay = None

		self.maintenance_frequency = 256 # in task cycles

		self._logfile = sys.stderr

		# f.system.events.Interface instance
		self.kernel = None

		self._init_exit()
		self._init_fabric()
		self._init_taskq()
		self._init_system_events()
		# XXX: does not handle term/void cases.
		self._init_traffic()

	def _init_exit(self):
		self._exit_stack = contextlib.ExitStack()
		self._exit_stack.__enter__()

	def _init_system_events(self):
		self.system_event_connections = {}
		self.system_event_connect(('signal', 'terminal.query'), None, self.report)

	def _init_fabric(self):
		self.fabric = Fabric(self)

	def _init_taskq(self, Queue=collections.deque):
		self.loading_queue = Queue()
		self.processing_queue = Queue()
		self._tq_maintenance = set()

	def _init_traffic(self, Matrix=Matrix):
		execute = functools.partial(self.fabric.critical, self, io_adapter)
		ix = Matrix(io_adapter, execute = execute)
		__traffic_index__[self] = ix

	def void(self):
		"""
		# Tear down the existing logical process state. Usually used internally after a
		# physical process fork.
		"""

		# normally called in fork
		self._init_exit()
		self._init_fabric()
		self._init_taskq()
		self._init_system_events()
		self.kernel.void()
		self.kernel = None
		self.iomatrix.void()

	def report(self, target=sys.stderr):
		"""
		# Report a snapshot of the process' state to the given &target.
		"""

		target.write("[%s]\n" %(libtime.now().select('iso'),))
		for unit in set(__process_index__[self].values()):
			unit.report(target)

	def __repr__(self):
		return "{0}(identity = {1!r})".format(self.__class__.__name__, self.identity)

	actuated = True
	terminated = False
	terminating = None
	interrupted = None
	def structure(self):
		"""
		# Structure information for the &Unit device entry.
		"""
		sr = ()

		# processing_queue is normally empty whenever report is called.
		ntasks = sum(map(len, (self.loading_queue, self.processing_queue)))
		nunits = len(__process_index__[self]) - 1

		p = [
			('pid', process.current_process_id),
			('tasks', ntasks),
			('threads', len(self.fabric.threading)),
			('units', nunits),
			('executable', sys.executable),

			# Track basic (task loop) cycle stats.
			('cycles', self.cycle_count),
			('frequency', None),
			('decay', self.cycle_start_time_decay),
		]

		python = os.environ.get('PYTHON', sys.executable)
		if python is not None:
			p.append(('python', python))

		return (p, sr)

	def maintain(self, task):
		"""
		# Add a task that is repeatedly executed after each task cycle.
		"""

		if task in self._tq_maintenance:
			self._tq_maintenance.discard(task)
		else:
			self._tq_maintenance.add(task)

	def error(self, context, exception, title = "Unspecified Execution Area"):
		"""
		# Exception handler for the &Representation instance.

		# This handler is called for unhandled exceptions.
		"""

		exc = exception
		exc.__traceback__ = exc.__traceback__.tb_next

		# exception reporting facility
		formatting = traceback.format_exception(exc.__class__, exc, exc.__traceback__)
		formatting = ''.join(formatting)

		self.log("[Exception from %s: %r]\n%s" %(title, context, formatting))

	def maintenance(self):
		# tasks to run after every cycle
		tasks = list(self._tq_maintenance)

		for task in tasks:
			try:
				task() # maintenance task
			except BaseException as e:
				self.error(task, e, title = 'Maintenance',)

	def loop(self, partial=functools.partial, BaseException=BaseException):
		"""
		# Internal loop that processes the task queue. Executed by &boot in a thread
		# managed by &fabric.
		"""

		time_snapshot = libtime.now
		ix = self.iomatrix
		cwq = self.processing_queue # current working queue; should be empty at start
		nwq = self.loading_queue # next working queue
		sec = self.system_event_connections

		task_queue_interval = 2
		default_interval = sys.getswitchinterval() / 5
		setswitchinterval = sys.setswitchinterval

		# discourage switching while processing task queue.
		setswitchinterval(2)

		while 1:
			self.cycle_count += 1 # bump cycle
			self.cycle_start_time = time_snapshot()
			self.cycle_start_time_decay = 1 # Incremented by main thread.

			# The processing queue becomes the loading and the loading becomes processing.
			self.processing_queue, self.loading_queue = cwq, nwq = nwq, cwq
			append = nwq.append

			while cwq:
				# consume queue
				try:
					pop = cwq.popleft
					while cwq:
						task = pop()
						task() # perform the enqueued task
				except BaseException as e:
					self.error(task, e, title = 'Task',)

			# This appears undesirable, but the alternative
			# is to run force for each process local I/O event.
			# Presuming that some I/O has occurred while processing
			# the queue is not terribly inaccurate.
			ix.activity()

			events = ()
			waiting = (not nwq and not cwq) # both are empty.

			if self._tq_maintenance and (waiting or self.cycle % self.maintenance_frequency == 0):
				# it's going to wait, so run maintenance
				# XXX need to be able to peek at the kqueue events
				self.maintenance()

			try:
				# Change the interval to encourage switching in Python threads.
				setswitchinterval(default_interval)

				with self.kernel:
					# Sets a flag inside the kernel structure indicating
					# that a wait is about to occur; if the flag isn't
					# set, a user event is not sent to the kqueue as it
					# is unnecessary.

					if waiting:
						events = self.kernel.wait()
					else:
						# the next working queue has items, so don't bother waiting.
						events = self.kernel.wait(0)
			finally:
				setswitchinterval(2)

			# process unix signals and child exit events
			for event in events:
				remove_entry = False

				if event[0] == 'process':
					# Defer read until system event connect.
					# Might allow SIGCHLD support on linux.
					event = ('process', event[1])
					args = (event[1], execution.reap(event[1]),)
					remove_entry = True
				elif event[0] == 'alarm':
					append(event[1])
					continue
				else:
					args = ()

				if event in sec:
					callback = sec[event][1] # system_event_connections
					if remove_entry:
						# process events only occur once
						del sec[event]

					append(partial(callback, *args))
				else:
					# note unhandled system events
					print('unhandled event', event)

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

	def _enqueue(self, *tasks):
		self.loading_queue.extend(tasks)

	def cut(self, *tasks):
		"""
		# Impose the tasks by prepending them to the next working queue.

		# Used to enqueue tasks with "high" priority. Subsequent cuts will
		# precede the earlier ones, so it is not appropriate to use in cases were
		# order is significant.
		"""

		self.loading_queue.extendleft(tasks)
		self.kernel.force()

	def enqueue(self, *tasks):
		"""
		# Enqueue a task to be ran.
		"""

		self.loading_queue.extend(tasks)
		self.kernel.force()
