"""
# Support for running tests without full system/executable contexts.
"""
import collections
from .. import core

class ExitController(object):
	"""
	# Root controller for tests.
	"""
	def __init__(self):
		self.exits = []
		self.callbacks = collections.defaultdict(list)
		self.interrupts = []

	def exited(self, processor):
		self.exits.append(processor)

	def exit_event_connect(self, subject, cb):
		self.callbacks[subject].append(cb)

	def interrupt(self, by=None):
		self.interrupts.append(by)

class Executable(object):
	"""
	# Critical difference between test.library.Context
	# and io.library.Context is that tasks must be explicitly
	# ran in order to perform them.
	"""

	def __init__(self):
		self.tasks = []
		self.faults = []

	def associate(self, processor):
		processor.executable = self

	def enqueue(self, *tasks, controller=None):
		self.tasks.extend(tasks)

	def faulted(self, resource):
		self.faults.append(resource)
		faultor = resource.controller
		faultor.interrupt(resource)
		if faultor.controller:
			faultor.controller.exited(faultor)

	def __call__(self, times=1):
		# Drain task queue n-times.

		for x in range(times):
			l = len(self.tasks)
			e = self.tasks[:l]
			del self.tasks[:l]
			for x in e:
				x()

	def flush(self, maximum=128):
		i = 0
		while self.tasks:
			self()
			i += 1
			if i > maximum:
				raise Exception('exceeded maximum iterations for clear test context task queue')

	def defer(self, mt):
		pass

	def cancel(self, task):
		pass

	def _io_attach(self, *channel):
		pass

class SystemChannel(object):
	link = None
	resource = None

	def k_transition(self):
		pass

	def acquire(self, obj):
		self.resource = obj

	def subresource(self, obj):
		self.controller = obj

	def process(self, event):
		pass

class Root(object):
	_pexe_contexts = ('executable', 'enqueue')

	def __init__(self):
		self.exits = []

	def exited(self, procs):
		self.exits.append(procs)

	controller = None

	def enqueue(self, task):
		# Fires immediately at root level.
		task()

	def dispatch(self, proc):
		self.processor = proc
		proc.subresource(self)
		proc.actuate()

def sector(count=1):
	"""
	# Construct a root Sector and Context for testing.
	"""
	ctx = Executable()
	yield ctx
	for x in range(count):
		sect = core.Sector()
		sect.executable = ctx
		sect.enqueue = ctx.enqueue
		sect._pexe_contexts = ('enqueue', 'executable',)
		x = ExitController()
		sect.controller = x
		sect.CONTROLLER = x
		sect.actuate()
		yield sect
