"""
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

	def enqueue(self, task, controller=None):
		self.tasks.append(task)

	def __call__(self):
		l = len(self.tasks)
		for x in self.tasks:
			x()
		del self.tasks[:l]

	def defer(self, mt):
		pass

	def cancel(self, task):
		pass

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

	controller = None

	def process(self, proc):
		self.processor = proc
		proc.subresource(self)
