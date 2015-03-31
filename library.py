"""
Commons area. Most functionality lives in nucleus modules with descriptive names.
"""
from ..scheduling import lib
from ..traffic import lib as trafficlib
from ..fork import lib as forklib

def perform_io_events(events):
	while events:
		link, delta = events.popleft()
		flow, kio = link
		try:
			kio._io_event(flow, delta)
		except:
			# XXX: note 
			raise

def dispatch_io_events(arg):
	junction, q = arg
	junction.link.enqueue(perform_io_events, q)

def context_io_events(self,
	junction,
	Queue = collections.deque,
	snapshot = trafficlib.Delta.snapshot,
):
	q = Queue()
	add = q.append
	for x in junction.transfer():
		add((x.link, snapshot(x)))

	return (junction, q)

def augment(ctx):
	exe = functools.partial(ctx.weave, forklib.critical, task)
	#: Intercontext I/O Manager
	interchange = trafficlib.Interchange(
		trafficlib.Adapter.create(dispatch_io_events, context_io_events),
		execute = exe
	)
	forklib.fork_child_cleanup.add(interchange)
	ctx.augment(interchange)

class KIO(Transformer):
	__slots__ = ('transit', '_queue',)

	def __init__(self, transit, Queue = collections.deque):
		self.transit = transit
		self._queue = Queue()

	def process(self, flow, data):
		if not self._queue:
			self._queue.extend(data)
			self.transit.acquire(self._queue.popleft())
		else:
			self._queue.extend(data)

	def _io_event(self, flow, delta):
		# Executed in main task queue by deliever_io_events

		# *MUST* rely on exhaust events here. If we peek ahead of the
		# event callback, we may run a double acquire().
		xfer, demand, term = delta

		if xfer is not None:
			# send transfer regardless of termination
			self.emit((xfer,))

		if term:
			flow.reduce(self)
		elif demand is not None and self._queue:
			# XXX: May race with process()
			demand(self._queue[0])
			self._queue.popleft()

class Throttle(Transformer):
	"""
	Transformer tracking flow rate at a particular point raising
	obstructions in situations of rate violations.
	"""

	def process(self, flow, payload):
		self.emit(flow, payload)
