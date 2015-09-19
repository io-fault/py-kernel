"""
Abstract Base Classes and common data structures.
"""
import abc

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

	@abc.abstractmethod
	def actuate(self):
		"""
		Signal the &Resource that it must be prepared for use after the method call exits.

		Can be &None.
		"""

class Transformer(Resource, metaclass=abc.ABCMeta):
	"""
	An object that manages a transformation and its dependent state.
	"""

	@property
	@abc.abstractmethod
	def retains(self):
		"""
		Whether or not the Transformer is capable of retaining partial events or buffers events.
		Used by &Flow.drain operations determine the need for continuation.
		"""
		return False

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

class Processor(Resource, metaclass = abc.ABCMeta):
	"""
	A resource that performs abstract processing.
	"""

	@abc.abstractmethod
	def terminate(self, by=None):
		"""
		Cause the termination of the Processor.
		Termination may not be immediate and is subjected to &Processor specific logic.
		"""

	@abc.abstractmethod
	def interrupt(self, by):
		"""
		Interrupt the processor terminating work.

		Interrupt is used exclusively by external Resources. Usually used for administrative
		interrupts.
		"""

	@abc.abstractmethod
	def atexit(self, callback):
		"""
		Register the callback to be executed when the &Processor exits.

		The callback will be executed when the &Processor has been detached from
		the &Resource.controller.
		"""

	@property
	@abc.abstractmethod
	def product(self):
		"""
		An attribute holding the product of a &Processor. Essentially, a return object, but
		normally unused.
		"""

	@property
	@abc.abstractmethod
	def exception(self):
		"""
		The exception attributed to the exit of the &Processor.
		"""

	@property
	@abc.abstractmethod
	def cascades(self):
		"""
		Whether or not the failure is inherited by the &Resource.controller.

		Defaults to &False for &Sector classes.
		"""

class Sector(Processor, metaclass = abc.ABCMeta):
	"""
	A group of &Processor instances. The set of Processors are organized
	by their type, but have no name. Sector subclasses can be made in
	order to provide access to the subprocessors.
	"""

class Unit(Processor, metaclass = abc.ABCMeta):
	"""
	A logical process used contain a set of units.
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

class Flow(Processor, metaclass=abc.ABCMeta):
	"""
	A sequence of &Transformer instances.
	"""

	@abc.abstractmethod
	def terminate(self, by=None):
		"""
		Initiate the termination of the &Flow; causes the &Flow to be drained
		then terminated by signalling the &Resource.controller of its exit.
		"""

	@abc.abstractmethod
	def drain(self, callback=None):
		"""
		Instruct the &Transformer sequence to drain any buffered events.

		Used when a checkpoint has been reached in a protocol, and as the
		signalling mechanism for completing termination.
		"""

	@abc.abstractmethod
	def watch(self, obstructed, cleared):
		"""
		Register callbacks to be executed whenever an obstruction is placed and cleared.
		"""

	@abc.abstractmethod
	def obstruct(self, obstruction, signal=None, condition=None):
		"""
		Note an obstruction on the &Flow signalling any callbacks registered
		by &watch.
		"""

	@abc.abstractmethod
	def clear(self, obstruction):
		"""
		Clear the cited &obstruction.

		If there are no remaining obstructions, signal any callbacks registered with &watch.
		"""

class Projection(object, metaclass=abc.ABCMeta):
	"""
	Object managing the credentials of an arbitrary entity.
	"""

	@property
	@abc.abstractmethod
	def entity(self):
		"""
		The entity that is driving the transactions of the Unit.
		The conceptual source of the events.
		"""

	@property
	@abc.abstractmethod
	def role(self):
		"""
		The role being fulfilled by the entity; usually subaccounts
		or composite entity positions (salesperson, engineer, etc).
		"""

	@property
	@abc.abstractmethod
	def credentials(self):
		"""
		A finite map of systems and their designated credentials.
		Arbitrary identifiers can be used, but an identifier of the relevant system
		is usually ideal.
		"""

	@property
	@abc.abstractmethod
	def authorization(self):
		"""
		A finite map of authorization tokens acquired.
		"""

	@property
	@abc.abstractmethod
	def transactions(self):
		"""
		A set of transactions being managed by the Unit.
		Transactions represent active work and the contents
		of this set may decide whether or not the unit may be reaped.
		"""

