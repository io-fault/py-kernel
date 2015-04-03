"""
Abstract Base Classes and common data structures.
"""
import abc

class Event(object, metaclass = abc.ABCMeta):
	"""
	Objects used to signal the occurrence of change.
	"""

	@property
	@abc.abstractmethod
	def kind(self):
		"""
		The kind of event. 
		"""

	@abc.abstractmethod
	def cancel(self):
		"""
		Attempt to cancel the event from occurring.
		"""

class Kind(object, metaclass = abc.ABCMeta):
	"""
	An object describing an Event.
	"""

	@abc.abstractmethod
	def __str__(self):
		pass

class Hazard(metaclass=abc.ABCMeta):
	"""
	An object exposing a set of events as a potential problem.
	Hazards are, in essence, warnings that exist for periods of time associated with the
	objects that caused them.
	"""

class Resource(metaclass=abc.ABCMeta):
	pass

class Flow(metaclass=abc.ABCMeta):
	pass

@fault
class Transformer(metaclass=abc.ABCMeta):
	"""
	An object that manages a transformation and its dependent state.
	"""
	@abc.abstractmethod
	def process(self, sequence):
		"""
		Instruct the transformer to process the @sequence immediately.
		"""
		pass

	@abc.abstractmethod
	def emit(self, seq):
		"""
		Method used by @process to send the sequence to the linked transformer.
		"""
		pass
