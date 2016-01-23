"""
Adapter for using &..traffic with &.library.Flow instances in &..io applications.

Specifically geared for &.library.KernelPort instances.

! WARNING:
	Needs a semaphore to block before overflowing the queue.
"""

import sys
import functools
import collections
from ..traffic import library

allocate = library.kernel.Junction.rallocate

# This is executed by the main io.library task queue of a SystemProcess instance.
# It ends up being a sub-queue for I/O events and has similar logic for managing
# exceptions.

def deliver_io_events(junction, events):
	"""
	Send the individual &events originally prepared by &separate_io_events to
	their associated &.library.KernelPort Transformers.
	"""

	popevent = events.popleft

	while events:
		kp = link = delta = flow = None
		# the double loop here is keep the primary loop inside
		# the try/except
		try:
			while events:
				event = popevent()

				link, delta = event
				kp = link
				if kp is None:
					link = None
					continue

				# *MUST* rely on exhaust events here. If we peek ahead of the
				# event callback, we may run a double acquire().
				xfer, demand, term = delta

				if xfer is not None:
					# send transfer regardless of termination
					# data may be transferred while the termination
					# condition is present, so its important it gets sent
					# prior to running the KernelPort's termination.
					kp.inject((xfer,))

				if term:
					kp.terminated()
					# Ignore termination for None links
				elif demand is not None:
					kp.transition()

				link = None
		except Exception as exception:

			try:
				if link is None:
					# failed to unpack the kp and delta from event
					# generally this shouldn't happen and usually refers
					# to a programming error in io.
					junction.link.error((junction, event), exception)
				else:
					flow = kp.controller
					flow.fault(exception, kp)
					flow.context.process.error(flow, exception, title="I/O")
			except Exception as exc:
				junction.link.context.process.error((junction, event), exc)

def synchronize_io_events(arg, partial=functools.partial):
	"""
	Send the event queue to the main task queue.
	Enqueue's &deliever_io_events with the queue constructed by &separate_io_events.
	"""

	junction, q = arg
	if not q:
		return

	# junction.link is a io.library.LogicalProcess
	junction.link.context.enqueue(partial(deliver_io_events, junction, q))

def separate_io_events(
		junction,
		Queue=collections.deque,
		snapshot=library.Delta.snapshot,
		iter=iter,
		MemoryError=MemoryError,
	):
	"""
	Process the junction's transfer and construct a queue of I/O events.
	This is executed inside a thread managed by the interchange and *cannot* deliever
	the events to Transformers. &syncrhonize_io_events is used to deliver the queue
	for processing in the SystemProcess's task queue.
	"""

	# In a thread *outside* of the task queue, so we can't
	# run process() methods on transformers.
	# Build the transfer set for processing in the task q.

	q = Queue()
	add = q.append
	i = iter(junction.transfer())

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
			# THIS BLOCKS I/O FOR THE ENTIRE UNIT
			raise

	return (junction, q)

adapter = library.Adapter(synchronize_io_events, separate_io_events)
