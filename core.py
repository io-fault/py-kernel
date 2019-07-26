"""
# Core data types and classes.
"""
import typing
import functools
import builtins
import operator
import weakref
import collections
import itertools
import traceback
import heapq

from ..time import types as timetypes
from ..time import sysclock

def set_actuated(processor):
	processor._pexe_state = 1
	return processor

def set_terminated(processor):
	processor._pexe_state = -1
	return processor

class Join(object):
	"""
	# An object whose purpose is to join the completion of multiple
	# processors into a single event. Joins are used to simplify coroutines
	# whose progression depends on a set of processors instead of one.

	# Joins also enable interrupts to trigger completion events so that
	# failures from unrelated Sectors can be communicated to callback.

	# [ Properties ]

	# /dependencies/
		# The original set of processors as a dictionary mapping
		# given names to the corresponding &Processor.

	# /pending/
		# The current state of pending exits that must
		# occur prior to the join-operation's completion.

	# /callback/
		# The callable that is performed after the &pending
		# set has been emptied; defined by &atexit.
	"""

	__slots__ = ('dependencies', 'pending', 'callback')

	def __init__(self, **processors):
		"""
		# Initialize the join with the given &processor set.
		"""

		self.dependencies = processors
		self.pending = set(processors.values())
		self.callback = None

	def connect(self):
		"""
		# Connect the &Processor.atexit calls of the configured
		# &dependencies to the &Join instance.
		"""

		for x in self.dependencies.values():
			x.atexit(self.exited)

		return self

	def __iter__(self, iter=iter):
		"""
		# Return an iterator to the configured dependencies.
		"""

		return iter(self.dependencies.values())

	def __getitem__(self, k):
		"""
		# Get the dependency the given identifier.
		"""

		return self.dependencies[k]

	def exited(self, processor):
		"""
		# Record the exit of the given &processor and execute
		# the &callback of the &Join if the &processor is the last
		# in the configured &pending set.
		"""

		self.pending.discard(processor)

		if not self.pending:
			# join complete
			self.pending = None

			cb = self.callback
			self.callback = None; cb(self) # clear callback to signal completion

	def atexit(self, callback):
		"""
		# Assign the callback of the &Join.

		# If the &pending set is empty, the callback will be immediately executed,
		# otherwise, overwrite the currently configured callback.

		# The &callback is executed with the &Join instance as its sole parameter.

		# [ Parameters ]

		# /callback/
			# The task to perform when all the dependencies have exited.
		"""

		if self.pending is None:
			callback(self)
			return

		self.callback = callback

class Condition(object):
	"""
	# A *reference* to a logical expression or logical function.

	# Conditional references are constructed from a subject object, attribute path, and parameters.
	# Used to clearly describe the objects that participate in a logical conclusion of interest.

	# Used by &Flow instances to describe the condition in which an obstruction is removed.
	# Conditions provide introspecting utilities the capacity to identify the cause of
	# an obstruction.
	"""

	__slots__ = ('focus', 'path', 'parameter')

	def __init__(self, focus, path, parameter = None):
		"""
		# [ Parameters ]
		# /focus/
			# The root object that is safe to reference
		# /path/
			# The sequence of attributes to resolve relative to the &focus.
		# /parameter/
			# Determines the condition is a method and should be given this
			# as its sole parameter. &None indicates that the condition is a property.
		"""
		self.focus = focus
		self.path = path
		self.parameter = parameter

	def __bool__(self):
		condition = self.attribute()

		if self.parameter is not None:
			return condition(self.parameter)
		else:
			# property
			return condition

	def __repr__(self):
		if self is Inexorable:
			return 'Inexorable'

		try:
			attval = self.attribute()
		except:
			attval = '<exception>'

		return "<Condition [%r].%s == %r>" %(
			self.focus, '.'.join(self.path), attval
		)

	def attribute(self, ag=operator.attrgetter):
		return ag('.'.join(self.path))(self.focus)

# A condition that will never be true.
Inexorable = Condition(builtins, ('False',))

class Resource(object):
	"""
	# Base class for &Processor.

	# [ Properties ]
	# /controller/
		# The &Resource containing this &Resource.
	"""

	context = None

	def _unset_controller(self):
		return None
	controller_reference = _unset_controller
	del _unset_controller

	def _dereference_controller(self):
		return self.controller_reference()

	def _set_controller_reference(self, obj, Ref = weakref.ref):
		self.controller_reference = Ref(obj)

	controller = property(
		fget = _dereference_controller,
		fset = _set_controller_reference,
		doc = "Direct ascending resource containing this resource."
	)
	del _dereference_controller
	del _set_controller_reference

	def controllerstack(self):
		"""
		# Return the stack of controllers of the given &Resource. Excludes initial resource.
		"""

		stack = []
		obj = self.controller

		while obj is not None:
			add(obj)
			obj = obj.controller

		return stack

	@property
	def sector(self, isinstance=isinstance):
		"""
		# Identify the &Sector holding the &Resource by scanning the &controller stack.
		"""

		c = self.controller
		while c and not isinstance(c, Sector):
			c = c.controller

		return c

	def __repr__(self):
		c = self.__class__
		mn = c.__module__.rsplit('.', 1)[-1]
		qn = c.__qualname__

		return '<%s.%s at %s>' %(
			mn, qn, hex(id(self))
		)

	def subresource(self, ascent:'Resource', Ref=weakref.ref):
		"""
		# Assign &ascent as the controller of &self and inherit its &Context.
		"""

		self._pexe_contexts = ascent._pexe_contexts
		for field in ascent._pexe_contexts:
			setattr(self, field, getattr(ascent, field))
		self.controller_reference = Ref(ascent)

	def relocate(self, ascent):
		"""
		# Relocate the Resource into the &ascent Resource.

		# Primarily used to relocate &Processors from one sector into another.
		# Controller resources may not support move operations; the origin
		# location must support the erase method and the destination must
		# support the acquire method.
		"""

		controller = self.controller
		ascent.acquire(self)
		controller.eject(self)

	def structure(self):
		"""
		# Returns a pair, a list of properties and list of subresources.
		# Each list contains pairs designating the name of the property
		# or resource and the object itself.

		# The structure method is used for introspective purposes and each
		# implementation in the class hierarchy will be called (&sequence) in order
		# to acquire a reasonable representation of the Resource's contents.

		# Implementations are used by &.library.format and &.library.sequence.
		"""

		return None

class ExceptionStructure(object):
	"""
	# Exception associated with an interface supporting the sequencing of processor trees.
	"""

	actuated=True
	terminated=False
	interrupted=False
	def __init__(self, identity, exception):
		self.identity = identity
		self.exception = exception

	def __getitem__(self, k):
		return (self.identity, self)[k]

	def structure(self):
		# exception reporting facility
		exc = self.exception

		formatting = traceback.format_exception(exc.__class__, exc, exc.__traceback__)
		formatting = ''.join(formatting)

		p = [
			('traceback', formatting),
		]

		return (p, ())

class Processor(Resource):
	"""
	# A resource that maintains an abstract computational state. Processors are
	# awaitable and can be used by coroutines. The product assigned to the
	# Processor is the object by await.

	# Processor resources essentially manage state machines and provide an
	# abstraction for initial and terminal states that are often used.

	# State Transition Sequence.

		# # Instantiated
		# # Actuated
		# # Functioning
		# # Terminating
		# # Terminated

	# Where the functioning state designates that the implementation specific state
	# has been engaged. Often, actuation and termination intersect with implementation states.

	# The interrupted state is special; its used as a frozen state of the machine and is normally
	# associated with an exception. The term interrupt is used as it is nearly analogous with UNIX
	# process interrupts (unix.signal)`SIGINT`.

	# [ Engineering ]
	# The Processor state is managed using a set of booleans. Considering the
	# number of processors that will be present in any complex system, condensing
	# the storage requirements by using a bitmask would help reduce the memory
	# footprint.
	"""

	_pexe_state = 0 # defaults to "object initialized"
	_pexe_states = (
		('initialized', 0), # Created.
		('actuated', 1), # Placed in Execution Context and started.
		('terminating', 2), # Received and accepted termination request.
		('terminated', -1), # Termination completed and the processor will exit().
		('deallocating', 0), # Unused state.
	)
	_pexe_contexts = ()

	@property
	def actuated(self) -> bool:
		"""
		# Whether the processor has been actuated, normally within a Sector.
		"""
		return self._pexe_state != 0

	@property
	def terminating(self) -> bool:
		"""
		# Whether the processor has started terminate.
		"""
		return self._pexe_state == 2

	@property
	def terminated(self) -> bool:
		"""
		# Whether the processor has been terminated.
		"""
		return self._pexe_state == -1

	@property
	def status(self, _states={k:v for v,k in _pexe_states}):
		return _states[self._pexe_state]

	@property
	def interrupted(self) -> typing.Union[bool]:
		if self.controller:
			return self.controller.interrupted
		else:
			# No controller.
			return None

	# Origin of the interrupt or terminate
	interrupted = False
	terminator = None

	product = None
	exceptions = None

	@property
	def functioning(self):
		"""
		# Whether or not the Processor is functioning.
		# Indicates that the processor was actuated and is neither terminated nor interrupted.

		# ! NOTE:
			# Processors are functioning *during* termination; instances where
			# `Processor.terminating == True`.
			# Termination may cause limited access to functionality, but
			# are still considered functional.
		"""

		return self._pexe_state == 1 and not self.interrupted

	def actuate(self):
		"""
		# Initialize the Processor for use within the controlling Sector.

		# Initialization method called after a &Processor has been given execution context.
		# &Processor.actuate performs no actions and does not need to be called when
		# overridden.
		"""
		pass

	def start_termination(self):
		self._pexe_state = 2

	def finish_termination(self):
		self._pexe_state = -1
		self.exit()

	def terminate(self, by=None):
		"""
		# Terminate the Processor using &interrupt and exit.
		# If &self did not implement &interrupt, a &RuntimeError will be raised.
		"""

		if self.terminated:
			return False

		self.interrupt()
		if not self.interrupted:
			raise RuntimeError("processor was not interrupted by default termination")

		self.finish_termination()
		return True

	def interrupt(self, context=None):
		"""
		# Signal the Processor that the controlling Sector has been interrupted,
		# and all processing of events should cease immediately.

		# Subclasses that need to perform disconnects or cancellations should
		# implement this method in order to ensure that event processing stops.
		# However, interrupt procedures will automatically rewrite the &process
		# method to perform a no-op if invoked, so carefully written subclasses
		# may not have to perform any tasks at all.
		"""

		pass

	def fault(self, exception, association=None):
		"""
		# Note the given exception as an error on the &Processor.
		# Exceptions identified as errors cause the &Processor to exit.

		# Called internally when a task associated with a Processor raises
		# an exception. The controlling Sector will be interrupted and the
		# faulting Processor identified for subsequent scrutiny.
		"""

		if self.exceptions is None:
			self.exceptions = set()

		self.exceptions.add((association, exception))
		self.exit = (lambda: None) # Inhibit normal exit signals
		self.executable.faulted(self)

	def _fault_trap(self, trapped_task):
		try:
			trapped_task() # Executed relative to &Sector instance.
		except BaseException as exc:
			self.fault(exc)

	def critical(self, task, partial=functools.partial, trap=_fault_trap):
		"""
		# Enqueue a task associated with the sector so that exceptions cause the sector to
		# fault. This is the appropriate way for &Processor instances controlled by a sector
		# to sequence processing.
		"""
		self.enqueue(partial(trap, self, task))
	del _fault_trap

	def exit(self):
		"""
		# Exit the processor by signalling the controlling processor that termination
		# has completed.
		"""
		self._pexe_state = -1
		return self.controller.exited(self)

	def structure(self):
		"""
		# Provides the structure stack with at-exit callbacks.
		"""

		props = []
		sr = ()

		if self.product is not None:
			props.append(('product', self.product))

		if self.exceptions is not None:
			props.append(('exceptions', len(self.exceptions)))
			sr = [(ident, ExceptionStructure(ident, exc)) for ident, exc in self.exceptions]

		p = [
			x for x in [
				('terminator', self.terminator),
			] if x[1] is not None
		]
		props.extend(p)

		return (props, sr)

	def placement(self):
		"""
		# Define the set index to use when dispatched by a &Sector.

		# By default, &Sector instances place &Processor instances into
		# &set objects that stored inside a dictionary. The index used
		# for placement is allowed to be overridden in order to optimize
		# the groups and allow better runtime introspection.
		"""

		return self.__class__

	def substitute(self, processor):
		"""
		# Terminate the processor &self, but reassign the exit hooks to be performed
		# when the given &processor exits. &processor will be dispatched into the controlling
		# sector.
		"""

		raise NotImplemented

class Sector(Processor):
	"""
	# A processing sector; manages a set of &Processor resources according to their class.
	# Termination of a &Sector is solely dependent whether or not there are any
	# &Processor instances within the &Sector.

	# Sectors are the primary &Processor class and have protocols for managing projections
	# of entities (users) and their authorizing credentials.

	# [ Properties ]

	# /processors/
		# A divided set of abstract processors currently running within a sector.
		# The sets are divided by their type inside a &collections.defaultdict.

	# /scheduler/
		# The Sector local schduler instance for managing recurrences and alarms
		# configured by subresources. The exit of the Sector causes scheduled
		# events to be dismissed.

	# /exits/
		# Set of Processors that are currently exiting.
		# &None if nothing is currently exiting.
	"""

	scheduler = None
	exits = None
	processors = None
	product = None

	def iterprocessors(self):
		return itertools.chain.from_iterable(self.processors.values())

	def structure(self):
		p = ()
		sr = [(hex(id(x)), x) for x in self.iterprocessors()]
		return (p, sr)

	def __init__(self, *processors, Processors=functools.partial(collections.defaultdict,set)):
		sprocs = self.processors = Processors()
		for proc in processors:
			sprocs[proc.placement()].add(proc)

	def actuate(self):
		"""
		# Actuate the Sector by actuating its processors.
		# There is no guarantee to the order in which the controlled
		# processors are actuated.

		# Exceptions that occur during actuation fault the Sector causing
		# the *controlling sector* to exit. If faults should not cause
		# the parent to be interrupted, they *must* be dispatched after
		# &self has been actuated.
		"""

		try:
			for proc in list(self.iterprocessors()):
				proc.subresource(self)
				proc.actuate()
				proc._pexe_state = 1
		except BaseException as exc:
			self.fault(exc)

	def scheduling(self):
		"""
		# Initialize the &scheduler for the &Sector.
		"""
		sched = self.scheduler = Scheduler()
		sched.subresource(self)
		sched.actuate()
		sched._pexe_state = 1

	def eject(self, processor):
		"""
		# Remove the processor from the Sector without performing termination.
		# Used by &Resource.relocate.
		"""

		self.processors[processor.__class__].discard(processor)

	_sector_terminated = Processor.exit

	def terminate(self, by=None):
		if not super().terminate(by=by):
			return False

		if self.processors:
			# Rely on self.reap() to finish termination.
			for Class, sset in self.processors.items():
				for x in sset:
					x.terminate()
		else:
			# Nothing to wait for.
			self._sector_terminated()

		return True

	def interrupt(self, by=None):
		"""
		# Interrupt the Sector by interrupting all of the subprocessors.
		# The order of interruption is random, and *should* be insignificant.
		"""

		if self.interrupted:
			return

		self.interrupted = True
		self.interruptor = by

		if self.scheduler is not None:
			self.scheduler.interrupt()

		# Sectors set if they've been interrupted, so the
		# following general case will be no-ops.
		for sector in self.processors[Sector]:
			sector.interrupt()

		for Class, processor_set in self.processors.items():
			for processor in processor_set:
				processor.interrupt() # Class

		# exits are managed by the invoker

	def exited(self, processor, set=set):
		"""
		# Sector structure exit handler.

		# Called when a Processor has reached termination and should no longer
		# be contained within the Sector.
		"""

		if self.exits is None:
			self.exits = set()
			try:
				self.executable.enqueue(self.reap)
			except:
				self.exits.add(processor)
				self.reap()
				return

		self.exits.add(processor)

	def dispatch(self, processor:Processor):
		"""
		# Dispatch the given &processor inside the Sector.
		# Assigns the processor as a subresource of the
		# instance, affixes it, and actuates it.

		# Returns the result of actuation, the &processor.
		"""

		processor.subresource(self)
		self.processors[processor.placement()].add(processor)
		processor.actuate()
		processor._pexe_state = 1

		return processor

	def coroutine(self, gf):
		"""
		# Dispatches an arbitrary coroutine returning function as a &Coroutine instance.
		"""

		gc = Coroutine.from_callable(gf)
		self.processors[Coroutine].add(gc)
		gc.subresource(self)

		return gc.actuate()

	def _flow(self, series):
		x = series[0]
		self.dispatch(x)
		for n in series[1:]:
			x.f_connect(n)
			x = n
			self.dispatch(n)

	def reap(self, set=set):
		"""
		# Empty the exit set and check for sector completion.
		"""

		exits = self.exits
		if exits is None:
			# Warning about reap with no exits.
			return
		del self.exits

		struct = self.processors
		classes = set()

		for x in exits:
			slot = x.placement()
			struct[slot].discard(x)
			classes.add(slot)

		for c in classes:
			if not struct[c]:
				del struct[c]

		# Check for completion.
		self.reaped()

	def reaped(self):
		"""
		# Called once the set of exited processors has been reaped
		# in order to identify if the Sector should notify the
		# controlling Sector of an exit event..
		"""

		# reap/reaped is not used in cases of interrupts.
		if not self.processors and not self.interrupted:
			# no processors remain; exit Sector

			if self.scheduler is not None:
				# After termination has been completed, the scheduler can be stopped.
				#
				# The termination process is an arbitrary period of time
				# that may rely on the scheduler, so it is important
				# that this is performed here.
				self.scheduler.interrupt()

			self._sector_terminated()

	def placement(self):
		"""
		# Use &Interface.if_sector_placement if the sector has an Interface.
		# Otherwise, &Sector.
		"""

		return self.__class__

		# XXX: Old isolation mechanism for identifying origins of work.
		for if_proc in self.processors.get(Interface, ()):
			# Use the interface processor's definition if any.
			return if_proc.sector_placement()
		else:
			return self.__class__

class Scheduler(Processor):
	"""
	# Time delayed execution of arbitrary callables.

	# Manages the set of alarms and &Recurrence's used by a &Sector.
	# Normally, only one Scheduler exists per and each Scheduler
	# instance chains from an ancestor creating a tree of heap queues.

	# [ Engineering ]
	# The &update method needs to be corrected to avoid the &scheduled_reference
	# stopgap. Currently, the weakmethod is used to allow the storage of the
	# scheduled event in case a cancellation is needed. Cancellation works
	# using a set of events and &Scheduler needs each transition to be unique
	# in order to perform cancellation at all.

	# The entire management of scheduled &transition events needs to be
	# rewritten along with some tweaks to chronometry's scheduler.
	"""

	scheduled_reference = None
	x_ops = None

	def structure(self):
		sr = ()
		p = []
		return (p, sr)

	def actuate(self, DefaultDict=collections.defaultdict, TaskQueue=collections.deque):
		self._snapshot = sysclock.now # XXX: Inherit from System context.
		self._heap = []
		# RPiT to (Event) Id's Mapping
		self._tasks = DefaultDict(TaskQueue)
		self._cancellations = set()

		self.persistent = True

		controller = self.controller
		sched = getattr(controller, 'scheduler', None)

		if True:
			# System
			self.x_ops = (
				self.system.defer,
				self.system.cancel
			)
		else:
			controller = controller.controller

			while controller is not None:
				if controller.scheduler is not None:
					sched = controller.scheduler
					break
				controller = controller.controller
			else:
				raise RuntimeError("no scheduling ancestor")

			self.x_ops = (
				sched.defer,
				sched.cancel,
			)

	@staticmethod
	def execute_weak_method(weakmethod):
		return weakmethod()()

	def cancel(self, *events):
		"""
		# Cancel the scheduled events.
		"""
		# Update the set of cancellations immediately.
		# This set is used as a filter by Defer cycles.
		self._cancellations.update(events)

	def schedule(self, pit:timetypes.Timestamp, *tasks, now=sysclock.now):
		"""
		# Schedule the &tasks to be executed at the specified Point In Time, &pit.
		"""

		snapshot = self._snapshot()
		self.put(snapshot, snapshot.measure(pit), *tasks)

	def defer(self, measure, *tasks):
		"""
		# Defer the execution of the given &tasks by the given &measure.
		"""

		snapshot = self._snapshot()
		p = self.period(snapshot)

		self.put(snapshot, measure, *tasks)

		if p is None:
			self.update(snapshot)
		else:
			np = self.period(snapshot)
			if np < p:
				self.update(snapshot)

	def recurrence(self, callback):
		"""
		# Allocate a &Recurrence and dispatch it in the same &Sector as the &Scheduler
		# instance. The target will be executed immediately allowing it to identify
		# the appropriate initial delay.
		"""

		r = Recurrence(callback)
		self.controller.dispatch(r)
		return r

	def transition(self):
		"""
		# Execute the next task given that the period has elapsed.
		# If the period has not elapsed, reschedule &transition in order to achieve
		# finer granularity.
		"""

		if not self.functioning:
			# Do nothing if not inside the functioning window.
			return

		period = self.period
		get = self.get
		snapshot = self._snapshot()

		tasks = get(snapshot)
		for task_objects in tasks:
			try:
				# Resolve weak reference.
				measure, scheduled_task = task_objects

				if scheduled_task is not None:
					scheduled_task()
			except BaseException as scheduled_task_exception:
				raise
		else:
			p = period(snapshot)

			try:
				if p is not None:
					# re-schedule the transition
					self.update(snapshot)
				else:
					# falls back to class attribute; None
					del self.scheduled_reference
			except BaseException as scheduling_exception:
				raise

	def interrupt(self):
		# cancel the transition callback
		if self.scheduled_reference is not None:
			self.x_ops[1](self.scheduled_reference)

	def update(self, snapshot):
		"""
		# Update the scheduled transition callback.
		"""

		nr = weakref.WeakMethod(self.transition)
		if self.scheduled_reference is not None:
			self.x_ops[1](self.scheduled_reference)

		sr = self.scheduled_reference = functools.partial(self.execute_weak_method, nr)
		self.x_ops[0](self.period(snapshot), sr)

	def period(self, current):
		"""
		# The period before the next event should occur.
		"""
		try:
			smallest = self._heap[0]
			return smallest.__class__(smallest - current)
		except IndexError:
			return None

	def put(self, current, measure, *tasks, push=heapq.heappush) -> int:
		"""
		# Schedules the given events for execution.

		# [ Parameters ]

		# /current/
			# Snapshot of the scheduler's clock.
		# /measure/
			# Time to wait before executing the &tasks.
		# /tasks/
			# The tasks to perform at the given &measure relative to &current.
		"""

		pit = measure.__class__(measure + current)
		push(self._heap, pit)
		self._tasks[pit].extend(tasks)

	def get(self, current, pop=heapq.heappop, push=heapq.heappush):
		"""
		# Return all events whose sheduled delay has elapsed according to the clock's
		# snapshot, &current.
		"""
		events = []

		while self._heap:
			# repeat some work in case of concurrent pop
			item = pop(self._heap)
			overflow = item.__class__(current - item)

			# the set of callbacks have passed their time.
			if overflow < 0:
				# not ready; put it back
				push(self._heap, item)
				break
			else:
				# If an identical item has already been popped,
				# an empty set can be returned in order to perform a no-op.
				eventq = self._tasks.pop(item, ())
				while eventq:
					x = eventq.popleft()
					if x in self._cancellations:
						# filter any cancellations
						# schedule is already popped, so remove event and cancel*
						self._cancellations.discard(x)
					else:
						events.append((overflow, x))

		return events

class Recurrence(Processor):
	"""
	# Timer maintenance for recurring tasks.

	# Usually used for short term recurrences such as animations and human status updates.
	# Recurrences work by deferring the execution of the configured target after
	# each occurrence. This overhead means that &Recurrence is not well suited for
	# high frequency executions, but useful in cases where it is important
	# to avoid overlapping calls.
	"""

	def __init__(self, target):
		self.recur_target = target
		self._recur_inhibit = False

	def actuate(self):
		"""
		# Enqueue the initial execution of the recurrence.
		"""

		self.critical(self._recur_occur)

	def recur_execute(self):
		if self.terminated or self.interrupted:
			return None

		return self.recur_target()

	def _recur_occur(self):
		"""
		# Invoke a recurrence and use its return to schedule its next iteration.
		"""

		next_delay = self.recur_execute()

		if next_delay is None:
			if not self.interrupted and not self.terminated:
				self.terminate()
		else:
			self.controller.scheduler.defer(next_delay, self._recur_occur)

	def terminate(self):
		self.finish_termination()

	def interrupt(self):
		self.interrupted = True

class Context(Processor):
	"""
	# The base class for &Transaction Context processors.

	# Subclasses define the initialization process of a Transaction
	# and the structures used to provide depending processors with the
	# necessary information for performing their tasks.

	# [ Namespaces ]
	# Context Processors employ two hard namespaces in its methods.
	# The `xact_ctx_` and the `xact_`. Methods and properties
	# that exist under `xact_ctx_` refer to generic Context operations
	# whereas `xact_` refers to operations that primary effect the
	# &Transaction sector containing the context.
	"""

	def placement(self):
		return Context

	def require(self, identifier):
		pass

	def provide(self, identifier):
		"""
		# Export &self as a named context inherited by all descending processors.
		"""
		assert identifier is not None

		ctl = self.controller
		if identifier not in ctl._pexe_contexts:
			ctl._pexe_contexts = ctl._pexe_contexts + (identifier,)
			setattr(ctl, identifier, self)

	def xact_empty(self) -> bool:
		"""
		# Whether the Transaction has any processors aside from the Context.
		"""
		sector = self.controller
		ip = sector.iterprocessors()
		ctx = next(ip)

		try:
			next(ip)
		except StopIteration:
			return True

		return False

	def xact_exit_if_empty(self):
		"""
		# Check for processors other than &self, if there are none, exit the transaction.
		"""
		sector = self.controller
		sector.reap()

		ip = sector.iterprocessors()
		ctx = next(ip)

		try:
			next(ip)
		except StopIteration:
			super().terminate()
			self.exit()

	def xact_contextstack(self) -> typing.Iterable[Processor]:
		"""
		# The complete context stack of the &Transaction excluding &self.
		# First entry is nearest to &self; last is furthest ascent.
		"""
		s = self.controller

		while s is not None:
			s = s.controller
			try:
				yield s.xact_context
			except AttributeError:
				pass

	@property
	def xact_subxacts(self):
		return self.controller.processors[Transaction]

	def xact_dispatch(self, processor:Processor):
		"""
		# Dispatch the given &processor into the &Transaction.
		"""
		xact = self.controller
		xact.dispatch(processor)
		return self

	def xact_initialized(self):
		"""
		# Called when the Transaction Context has been fully initialized with respect to
		# the proposed event set determined by actuation.
		"""
		pass

	def xact_exit(self, xact):
		"""
		# Subtransaction &xact exited.
		"""
		pass

	def xact_void(self, xact):
		"""
		# All subtransactions exited; &xact was final.
		# Defaults to termination of the context and transaction exit.
		"""
		self.terminate()

	def interrupt(self):
		"""
		# Update Transaction Context callbacks to null operations.

		# Sets &interrupted to &True and should be called by subclasses if overridden.
		"""
		xact_event = (lambda x: None)
		self.xact_exit = xact_event
		self.xact_void = xact_event
		self.xact_dispatch = xact_event
		self.interrupted = True

class Transaction(Sector):
	"""
	# A &Sector with Execution Context.

	# Transactions are sectors with a single &Context instance that is used to manage
	# the state of the Sector. Regular Sectors exit when all the processors are shutdown,
	# and Transactions do too. However, the &Context is the controlling processor and
	# must be the last to exit.

	# [ Properties ]

	# /xact_context/
		# The Processor that will be dispatched to initialize the Transaction
		# Sector and control its effect. Also, the receiver of &Processor.terminate.
	"""

	@classmethod
	def create(Class, xc:Context):
		"""
		# Create a &Transaction sector with the given &Context initializaed
		# as the first Processor to be actuated.

		# This is the appropriate way to instantiate &Transaction instances
		"""

		xact = Class(xc)
		xact.xact_context = xc

		return xact

	def isinstance(self, ContextClass):
		"""
		# Whether the Transaction's context, &xact_context, is an instance of the given &ContextClass.
		"""
		return isinstance(self.xact_context, ContextClass)

	def terminate(self, by=None):
		"""
		# Invoke the &Context.terminate method of the &xact_context property.
		# The termination of the Transaction is managed entirely by the Context.
		"""

		return self.xact_context.terminate()

	def placement(self):
		"""
		# Define the set index to use when dispatched by a &Sector.

		# By default, &Sector instances place &Processor instances into
		# &set objects that stored inside a dictionary. The index used
		# for placement is allowed to be overridden in order to optimize
		# the groups and allow better runtime introspection.
		"""

		return Transaction

	def iterprocesses():
		yield self.xact_context
		yield from super().iterprocessors()

	def exited(self, processor):
		if processor.placement() == Transaction:
			# Signal context about subtransaction exit.
			self.xact_context.xact_exit(processor)
			subxacts = self.processors[Transaction] - (self.exits or set())

			if len(subxacts) <= 1:
				self.xact_context.xact_void(processor) # Signal empty transaction.

		return super().exited(processor)

class Executable(Context):
	"""
	# Transaction sequence created from an invocation.

	# [ Properties ]

	# /exe_identifier/
		# A, usually, unique identifier for the executable.
		# The transaction context that the executable is dispatched within determines
		# any constraints, if any.
	# /exe_invocation/
		# The primary set of parameters used by the executable.
	# /exe_faults/
		# The set of sectors that were faulted within the context; usually keyed by
		# the identifier of the processor that was blamed.
	# /exe_faults_count/
		# The total number of faults that occurred. In cases where faults have been
		# purged from &exe_faults, the count allows recognition of the purge.
	# /exe_queue/
		# The transactions to be executed in order to complete execution.
	"""

	def __init__(self, invocation, identifier=None, Queue=collections.deque):
		self.exe_identifier = identifier or self.__name__.lower()
		self.exe_invocation = invocation
		self.exe_faults = {}
		self.exe_faults_count = 0
		self.exe_queue = Queue()

	def actuate(self):
		self.provide('executable')
		self.controller.scheduling()

	def terminate(self):
		self.start_termination()
		i = self.controller.iterprocessors()
		next(i)
		for x in i:
			x.terminate()

	def xact_void(self, final):
		"""
		# Consume the next transaction in the queue.
		"""
		q = self.exe_queue
		if q:
			nxact = q.popleft()
			self.xact_dispatch(nxact)
		else:
			self.finish_termination()

	def exe_enqueue(self, xact_context):
		self.exe_queue.append(Transaction.create(xact_context))

	def exe_initialize(self):
		"""
		# Execute the enqueued transaction or cause the executable to exit.
		"""
		self.xact_void(None)

	def faulted(self, proc:Processor) -> None:
		"""
		# Place the sector into the faults directory using the hex identifier
		# as its name.
		"""

		self.exe_faults_count += 1
		self.exe_faults['@'+hex(id(proc))] = proc

		sector = proc.sector
		if sector.interrupted:
			# assume that the existing interruption
			# has already managed the exit.
			pass
		else:
			sector.interrupt()
			if not sector.terminated:
				# It wasn't interrupted and it wasn't terminated,
				# so it should be safe to signal its exit.
				sector.controller.exited(sector)

	def structure(self):
		p = [
			('exe_identifier', self.exe_identifier),
			('exe_faults', self.exe_faults_count),
			('exe_queue', self.exe_queue),
		]

		return (p, ())
