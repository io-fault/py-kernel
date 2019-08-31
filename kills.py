"""
# Fault inducing processors.
"""
import functools

from . import core

class Fatal(core.Processor):
	"""
	# Processor that faults the controlling Sector upon actuation.
	"""

	@classmethod
	def inject(Class, sector, event):
		fp = Fatal()
		sector.dispatch(fp)

	def actuate(self):
		self.critical(functools.partial(self.process, None))

	def process(self, event):
		raise Exception(event)

class Timeout(core.Processor):
	"""
	# Processor that faults when a timeout occurs.
	"""

	def __init__(self, remainder):
		self.fto_wait_time = remainder

	def actuate(self):
		self.sector.scheduler.defer(self.fto_wait_time, self.fto_execute)

	def terminate(self, by=None):
		"""
		# Cancel the effect of the timeout.
		"""
		if not super().terminate(by=by):
			return False
		self.sector.scheduler.cancel(self.fto_execute)
		self.exit()

	def fto_execute(self):
		if self.terminated:
			return
		self.fault(exc)
