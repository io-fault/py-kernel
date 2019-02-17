"""
# Provides asynchronous I/O core for &fault.kernel applications.

# [ Properties ]

# /allocate/
	# Access to &..system.io.Array.rallocate for Channel allocations.
# /adapter/
	# The &Adapter instance used by &.process.Representation to manage I/O events.
"""
import os
import sys
import contextlib
import operator
import itertools
import functools
import time

from ..system import io

allocate = io.Array.rallocate
TransitionViolation = io.TransitionViolation

# This class exists for documentation purposes only.
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
	def create(typ, endpoint, transformer):
		r =  typ(endpoint, transformer)
		hash(r) # must be hashable
		return r

	def __new__(typ, endpoint, transformer):
		return tuple.__new__(typ, (endpoint, transformer))

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
	def construct(typ, payload = None, demand = None, terminated = None):
		return typ((payload, demand, terminated))

	@classmethod
	def snapshot(typ, channel):
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

		return typ((channel.transfer(), demand, term))

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
		Terminated = TransitionViolation
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

adapter = Adapter(synchronize_io_events, separate_io_events)
