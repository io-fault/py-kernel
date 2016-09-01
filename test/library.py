"""
Support for running tests outside of a &.library.Unit environment.
"""

class Context(object):
	"""
	Critical difference between test.library.Context
	and io.library.Context is that tasks must be explicitly
	ran in order to perform them.
	"""

	process = None

	def __init__(self):
		self.tasks = []

	def associate(self, processor):
		self.association = lambda: processor
		processor.context = self

	def enqueue(self, *task, controller=None):
		self.tasks.extend(task)

	def attach(self, *ignored):
		pass # Tests don't use real transits.

	def __call__(self):
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

	def faulted(self, resource):
		self.faults.append(resource)
		faultor = resource.controller
		faultor.interrupt()
		if faultor.controller:
			faultor.controller.exited(faultor)

class Transit(object):
	link = None

	def acquire(self, obj):
		self.resource = obj

	def subresource(self, obj):
		self.controller = obj

	def process(self, event):
		pass

class Root(object):
	"Root Processor Mimic; core.Unit substitute."
	def __init__(self):
		self.exits = []

	def exited(self, procs):
		self.exits.append(procs)

	controller = None

	def process(self, proc):
		self.processor = proc
		proc.subresource(self)
		proc.actuate()
