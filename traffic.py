"""
Adapter for using the traffic library with io@:project.

Specifically geared for &library.Detour instances.
"""
import functools
import collections

from ..traffic import library

def deliver_io_events(junction, events):
	"""
	Send the individual &events originally prepared by &separate_io_events to
	their associated &Detour Transformers.
	"""
	while events:
		detour = link = delta = flow = None
		# the double loop here is keep the primary loop inside
		# the try/except
		try:
			while events:
				event = events.popleft()

				link, delta = event
				detour = link

				# *MUST* rely on exhaust events here. If we peek ahead of the
				# event callback, we may run a double acquire().
				xfer, demand, term = delta

				if xfer is not None:
					# send transfer regardless of termination
					detour.emission(xfer)

				if term:
					detour.terminate()
				elif demand is not None:
					detour.transition()

				link = None
		except Exception as ferr:
			if link is None:
				# failed to unpack the detour and delta from event
				# generally this shouldn't happen and usually refers
				# to a programming error in io.
				junction.link.exception(junction, event, ferr)
			else:
				detour.exception(ferr)

def synchronize_io_events(arg):
	"""
	Send the event queue to the main task queue.
	Enqueue's @deliever_io_events with the queue constructed by @separate_io_events.
	"""
	junction, q = arg
	# junction.link is a Division
	junction.link.context.enqueue(functools.partial(deliver_io_events, junction, q))

def separate_io_events(
	junction,
	Queue = collections.deque,
	snapshot = library.Delta.snapshot,
):
	"""
	Process the junction's transfer and construct a queue of I/O events.
	This is executed inside a thread managed by the interchange and *cannot* deliever
	the events to Transformers. @syncrhonize_io_events is used to deliver the queue
	for processing in the Context's task queue.
	"""
	# In a thread *outside* of the task queue, so we can't
	# run process() methods on transformers.
	# Build the transfer set for processing in the task q.

	q = Queue()
	add = q.append
	for x in junction.transfer():
		add((x.link, snapshot(x)))

	return (junction, q)

adapter = library.Adapter(synchronize_io_events, separate_io_events)
