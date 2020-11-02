"""
# &..kernel interfaces.
"""
import abc

class ProcessorState(object, metaclass=abc.ABCMeta):
	"""
	# An abstract processing unit.
	"""

	@property
	@abc.abstractmethod
	def controller(self):
		"""
		# The immediate ascendant referring to the instance.

		# Usually, this property should resolve a weak reference.
		"""

	@abc.abstractmethod
	def actuate(self):
		"""
		# Complete any necessary configuration and execute the Processor's primary functionality.
		"""

	@abc.abstractmethod
	def terminate(self):
		"""
		# Request termination; processors not supporting termination requests should raise an exception.
		"""

	@abc.abstractmethod
	def interrupt(self):
		"""
		# Instantaneously interrupt the processor prohibiting further state changes.

		# Endpoints receiving events should be patched to either ignore the event or raise an
		# exception.

		# Interrupts intend to maintain their internal state in case analysis is necessary.
		"""
