"""
Abstract Base Classes and common data structures.
"""
import abc

class Mechanism(metaclass = abc.ABCMeta):
	"""
	An arbitrary object performing, directly or indirectly, the necessary supporting
	functionality for a &Resource.
	"""

class Resource(metaclass = abc.ABCMeta):
	@property
	@abc.abstractmethod
	def context(self):
		"""
		A reference to the &Context that allocated the resource and defines its operating
		environment.
		"""

	@property
	@abc.abstractmethod
	def controller(self):
		"""
		The immediate ascendant referring to the &Resource. There is only one &controller
		per object and the reference held by the controller is intended to be the critical
		reference.
		"""

class Program(Resource, metaclass = abc.ABCMeta):
	"""
	A logical portion of a program.
	"""

	@property
	@abc.abstractmethod
	def identifier(self):
		"""
		The name of the Program. Used to identify a program from the logical process.
		"""

	@property
	@abc.abstractmethod
	def roots(self):
		"""
		A sequence listing the initialization functions of the Program.

		During initialization, the items of this sequence are called and given
		the &Program instance as its sole parameter.
		"""

	@property
	@abc.abstractmethod
	def structure(self):
		"""
		A dictionary tree whose leaves are initializors for the corresponding index
		entries that maintain the &Program's state.
		"""

	@property
	@abc.abstractmethod
	def index(self):
		"""
		A flat index whose keys are tuples specifying the path in the @tree.
		The values are containers of resources that make up state of the &Program.
		"""

class Transformer(Resource, metaclass=abc.ABCMeta):
	"""
	An object that manages a transformation and its dependent state in a context-free
	manner.
	"""
	@abc.abstractmethod
	def process(self, sequence):
		"""
		Instruct the transformer to process the @sequence immediately.
		"""
		pass

	@property
	@abc.abstractmethod
	def emit(self, event):
		"""
		Method used by @process to send the sequence to the linked transformer.

		Given that no connection is made and the Transformer is not a terminal,
		the method should raise an exception to denote the failure.
		"""
		pass

	@abc.abstractmethod
	def emission(self, event):
		"""
		Usually an indirect reference to the execution of the &emit property.
		This is used internally by some transformers in order to perform
		&Transformer local processing before passage.

		Joins that dispatch work or perform signalling often use the bound method form
		of this in order to have a consistent means of invoking &emit as the configuration
		of emit can vary.
		"""

class Join(Transformer, metaclass=abc.ABCMeta):
	"""
	An object that manages a transformation in a context-dependant manner.
	Joins are explicitly dependent on side-effects, &Mechanism, in order to perform their
	transformation.
	"""

class Flow(object, metaclass=abc.ABCMeta):
	@abc.abstractmethod
	def obstruct(self, by):
		"""
		Note an obstruction in the flow by the specified Transformer.
		"""
