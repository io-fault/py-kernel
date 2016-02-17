"""
Adapter for using &..traffic with &.library.Flow instances in &..io applications.

Specifically geared for &.library.KernelPort instances. The current design requires
that read transfers be tracked in order to know when more memory needs to be assigned
to the Transit. While this essentially ignores Traffic's exhaust events, it is nearly
a non-loss due to cases where rate tracking is desired.

! NOTE:
	Semaphores are *not* needed to throttle I/O as continuation is an effect of performing
	the transfer in the main task queue.

[ Properties ]

/allocate
	Access to &..traffic.kernel.Junction.rallocate for Transit
	allocations.
"""

import functools
import time
from ..traffic import library

allocate = library.kernel.Junction.rallocate

# This is executed by the main io.library task queue of a .process.Representation  instance.
# It ends up being a sub-queue for I/O events and has similar logic for managing
# exceptions.

def deliver_io_events(junction, events, iter=iter):
	"""
	Send the individual &events originally prepared by
	&separate_io_events to their associated &.library.KernelPort Transformers.
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
					kp.terminated() # 
					# Ignore termination for None links
				elif demand is not None:
					kp.transition() # Accept the next memory transfer.

				link = None
			else:
				complete = True # Done processing events.
		except BaseException as exception:
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
			except BaseException as exc:
				# Record exception of cleanup failure.
				# TODO: Note as cleanup failure.
				junction.link.context.process.error((junction, event), exc)

def synchronize_io_events(arg, partial=functools.partial):
	"""
	Send the event queue to the main task queue.
	Enqueue's &deliever_io_events with the queue constructed by &separate_io_events.
	"""

	junction, queue = arg
	if not queue:
		return # Nothing to do.

	# junction.link is a io.process.Representation()
	junction.link.context.enqueue(partial(deliver_io_events, junction, queue))

def separate_io_events(
		junction,
		Queue=list,
		snapshot=library.Delta.snapshot,
		iter=iter,
		MemoryError=MemoryError,
		sleep=time.sleep,
	):
	"""
	Process the junction's transfer and construct a sequence of I/O events.

	This is executed inside a thread managed by the interchange and *cannot* deliver
	the events to Transformers. &syncrhonize_io_events is used to deliver the queue
	for processing in the &.process.Representation's task queue.
	"""

	# In a thread *outside* of the task queue, so is inappropriate
	# to run process() methods on transformers.
	# Build the transfer set for processing in the task queue.

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
			# THIS BLOCKS I/O FOR THE Junction instance.
			while True:
				try:
					sleep(1)
					add((x.link, snapshot(x)))
					break
				except MemoryError:
					pass

	return (junction, q)

adapter = library.Adapter(synchronize_io_events, separate_io_events)
