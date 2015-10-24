"""
Abstract Base Classes and common data structures.

Defines the semantics of the &core classes.
"""
import abc

class Projection(object, metaclass=abc.ABCMeta):
	"""
	Object managing the credentials of an arbitrary entity.

	Used by &Sector instances.
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
		XXX: Probably remove this or move to Sector.

		A set of transactions being managed by the Unit.
		Transactions represent active work and the contents
		of this set may decide whether or not the unit may be reaped.
		"""

class Resource(metaclass = abc.ABCMeta):
	@property
	@abc.abstractmethod
	def context(self):
		"""
		A reference to the &Context and ultimately the &Process supporting the &Resource.
		"""

	@property
	@abc.abstractmethod
	def controller(self):
		"""
		The immediate ascendant referring to the &Resource. There is only one &controller
		per object and the reference held by the controller is intended to be the critical
		reference.

		Equivalent to the parent process of a unix system process.
		"""

class Processor(Resource, metaclass = abc.ABCMeta):
	"""
	A resource that performs abstract processing.
	"""

	@abc.abstractmethod
	def __init__(self):
		"""
		Initialization *should* not require parameters as &requisite is the appropriate
		interface. Initialization is intended to be little more than object allocation
		in order to allow pre-allocated pools of Processors to be used.
		"""

	@abc.abstractmethod
	def requisite(self, *args, **kw):
		"""
		Provide a set of requisites for the &Processor that are required prior
		to actuation of the Processor.

		Complex &Processors subclasses may require explicit invocation of a class
		qualified method in order for an instance to be ready for actuation.
		"""

	@abc.abstractmethod
	def actuate(self):
		"""
		Prepare the &Processor for activity; must be called prior to any &process
		invocations.

		Processors that are actuated and not terminated nor interrupted are said
		to be "functioning". A functioning Processor means that the state
		of the Processor is totally dependent on its implementation and thus
		subjective.
		"""

	@abc.abstractmethod
	def process(self, event, source = None):
		"""
		Formal message passing interface for &Processors.

		Ideally, all possible Processor states could be reached using &process.
		However, this is often not the case as its usually easier to split the
		functionality across a set of methods.
		"""

	@abc.abstractmethod
	def terminate(self, by=None):
		"""
		Initiate the termination state of the Processor.

		Termination may not be immediate and is subjected to &Processor specific logic.
		Some Processors may not support termination at all and invoke an interruption instead.

		The termination process should end in the Processor generating an exit event emitted
		to the controlling Processor. When an implementation (subclass) does not support
		termination, it should interrupt and signal exit itself.

		The termination process is revealed by setting the &terminating property to &True
		upon &terminate being invoked, and then to &False when termination has completed.
		Additionally, &terminated must be set to &True when termination has completed.
		"""

	@abc.abstractmethod
	def interrupt(self, by=None):
		"""
		Interrupt the processor prohibiting further state changes.

		Interrupts are primarily used in cases of exceptions and timeouts.
		It attempts to provide a means to manage Processor exits regardless of
		implementation state--being the difference between termination and interruption.

		Unlike termination, interrupts are immediate, and there is *no* "interrupting" state.

		Interrupting a Processor does *not* trigger exit events to be sent to the controlling
		Processor; rather it is up to the interruptor to determine how to proceed as the
		interrupt may have been inherited from a controlling &Sector; the Sector is exiting,
		not the descendant Processors.
		"""

	@abc.abstractmethod
	def atexit(self, callback):
		"""
		Register the callback to be executed when the &Processor exits.

		The callback will be executed when the &Processor has been detached from
		the &Resource.controller.

		If the &Processor is interrupted by a controlling &Sector, the exit handler
		will never be called.

		The &callback must be a callable that can accept a single parameter, the
		&Processor that exited.
		"""

	@property
	@abc.abstractmethod
	def product(self):
		"""
		An attribute holding the product of a &Processor.
		Essentially, a return object, but not always used.
		"""

	@property
	@abc.abstractmethod
	def exceptions(self):
		"""
		The set of exceptions associated with the &Processor.

		Used to track how a fault occurred.
		"""

class Transformer(Processor, metaclass=abc.ABCMeta):
	"""
	A &Processor whose termination process depends on the completion
	of the preceeding Transformer.
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
	def drain(self):
		"""
		Initiate a drain operation on the Transformer, if the &Transformer
		returns a not &None object, it is used to register a callback
		that is executed on completion. If &None is returned, it indicates
		that the drain operation was successfully completed.

		Drain operations are not entirely consistent with flushes in that
		they are not mere buffers.
		"""

	@abc.abstractmethod
	def emit(self, event):
		"""
		Property set by &Flow Processors to send an effect of the &process method downstream.
		"""

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

class Sector(Processor, metaclass = abc.ABCMeta):
	"""
	A group of &Processor instances. The set of Processors are organized
	by their type, but have no name. Sector subclasses can be made in
	order to provide named access to the subprocessors.

	Sectors are analogous to unix system processes.
	"""

	@property
	@abc.abstractmethod
	def projection(self) -> Projection:
		"""
		Defaults to &None, but provides access to any credentials of the user or group
		that is being represented by the &Sector.
		"""

	@property
	@abc.abstractmethod
	def scheduler(self):
		"""
		A &Processor controlled by the &Sector that provides scheduling
		support for controlled &Processor instances referenced by the &Sector.

		This &Processor does *not* block the exit of the &Sector;
		rather it will be interrupted and remain as a property on the Sector
		until its garbage collected.

		Using these schedulers implies that events should only occur if the
		&Sector is Functioning.
		"""

class Unit(Processor, metaclass = abc.ABCMeta):
	"""
	The set of root &Processor instances that make up the Unit.
	"""

	@property
	@abc.abstractmethod
	def identity(self):
		"""
		The name of the Unit. Used by the &Process to distinguish &Unit instances.
		"""

	@property
	@abc.abstractmethod
	def roots(self):
		"""
		A sequence listing the initialization functions of the &Unit.

		During initialization, the items of this sequence are called and given
		the &Program instance as its sole parameter.

		Exceptions from roots will raise a Panic.
		"""

	@property
	@abc.abstractmethod
	def hierarchy(self):
		"""
		A dictionary tree whose leaves are initializors for the corresponding index
		entries that maintain the &Unit's state.
		"""

	@property
	@abc.abstractmethod
	def index(self):
		"""
		A flat index whose keys are tuples specifying the path in the @tree.
		The values are containers of resources that make up state of the &Program.
		"""

	@property
	@abc.abstractmethod
	def ports(self):
		"""
		The sets of interfaces used to gain work.

		For servers, this is where the listening Interfaces are managed.

		Exists in the hierarchy as "/dev/ports".
		"""

	@property
	@abc.abstractmethod
	def scheduler(self):
		"""
		The root &Scheduler instance used by all controlled Resources.

		Exists in the hierarchy as "/dev/scheduler".
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

		Flow termination is dependent on &drain completion.
		"""

	@abc.abstractmethod
	def drain(self, callback=None):
		"""
		Instruct the &Transformer sequence to drain any retained events.

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

