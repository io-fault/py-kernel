"""
# Core data types and classes.
"""
import typing
import functools
import builtins
import operator
import weakref
import collections

from ..time import library as libtime

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
	# Base class for the Resource and Processor hierarchy making up a fault.io process.

	# [ Properties ]

	# /context/
		# The execution context that can be used to enqueue tasks,
		# and provides access to the root &Unit.

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

	@property
	def unit(self):
		"""
		# Return the &Unit that contains this &Resource instance.
		"""
		return self.context.association()

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

		self.controller_reference = Ref(ascent)
		self.context = ascent.context

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

		# Implementations are used by &format and &sequence.
		"""

		return None

class Device(Resource):
	"""
	# A resource that is loaded by &Unit instances into (io.resource)`/dev`

	# Devices often have special purposes that regular &Resource instances do not
	# normally fulfill. The name is a metaphor for operating system kernel devices
	# as they are often associated with kernel features.
	"""

	@classmethod
	def connect(Class, unit):
		"""
		# Load an instance of the &Device into the given &unit.
		"""

		dev = Class()
		unit.place(dev, 'dev', Class.device_entry)
		dev.subresource(unit)

		return dev

@collections.abc.Awaitable.register
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

	# [ Properties ]
	# /terminating/
		# Whether the Processor is in a termination state. &None if
		# the Processor was never terminating.

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

	@property
	def actuated(self) -> bool:
		return self._pexe_state != 0

	@property
	def terminating(self) -> bool:
		return self._pexe_state == 2

	@property
	def terminated(self) -> bool:
		return self._pexe_state == -1

	@property
	def status(self, _states={k:v for v,k in _pexe_states}):
		return _states[self._pexe_state]

	def termination_started(self):
		self._pexe_state = 2

	def termination_completed(self):
		self._pexe_state = -1

	@property
	def interrupted(self) -> typing.Union[bool]:
		if self.controller:
			return self.controller.interrupted
		else:
			# No controller.
			return None

	# Origin of the interrupt or terminate
	terminator = None

	product = None
	exceptions = None

	# Only used by processor groupings.
	exit_event_connections = None

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

		return self._pexe_state > 0 and not self.interrupted

	def controlled(self, subprocessor):
		"""
		# Whether or not the given &Processor is directly controlled by &self.
		"""

		# Generic Processor has no knowledge of subresources.
		return False

	def actuate(self):
		"""
		# Initialize the Processor for use within the controlling Sector.
		"""
		pass

	def process(self, event):
		"""
		# Processing entry point for performing work of primary interest.
		"""

		pass

	def terminate(self, by=None):
		"""
		# Request that the Processor terminate.
		# Causes the Processor to progress into a `'terminating'` or `'terminated'` state
		# given that the Processor allows it.

		# Processors that do not support direct termination requests should document why
		# in their documentation strings.
		"""

		if not self.functioning or self.terminating:
			return False

		self.termination_started()
		self.terminator = by
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
		self.exit = (lambda x: x)
		self.context.faulted(self)

	def _fio_fault_trap(self, trapped_task):
		try:
			trapped_task() # Executed relative to &Sector instance.
		except BaseException as exc:
			self.fault(exc)

	def ctx_enqueue_task(self, task, partial=functools.partial, trap=_fio_fault_trap):
		"""
		# Enqueue a task associated with the sector so that exceptions cause the sector to
		# fault. This is the appropriate way for &Processor instances controlled by a sector
		# to sequence processing.
		"""
		self.context.enqueue(partial(trap, self, task))
	del _fio_fault_trap

	def exit(self):
		"""
		# Exit the processor by signalling the controlling processor that termination
		# has completed.
		"""
		self._pexe_state = -1
		return self.controller.exited(self)

	def atexit(self, exit_callback):
		"""
		# Register a callback to be executed when the Processor has been unlinked from
		# the Resource hierarchy.

		# The given callback is called after termination is complete and the Processor's
		# reference has been released by the controller. However, the controller backref
		# should still be available at this time.

		# The callback is registered on the *controlling resource* which must be a &Processor.

		# The &exit_callback will **not** be called if the &Processor was interrupted.
		"""

		if self.terminated:
			exit_callback(self) # Processor already exited.
		else:
			self.controller.exit_event_connect(self, exit_callback)

	def final(self):
		"""
		# Identify the &Processor as being final in that the exit of the processor
		# causes the sector to *terminate*. The &Sector will, in turn, invoke termination
		# on the remaining processors and exit when all of the processors have exited.
		"""
		self.controller.final = self
		self.atexit(lambda final: final.controller.terminate())

	def __await__(self):
		"""
		# Coroutine interface support. Await the exit of the processor.
		# Awaiting the exit of a processor will never raise exceptions with
		# exception to internal (Python) errors. This is one of the notable
		# contrasts between Python's builtin Futures and fault.io Processors.
		"""

		# Never signalled.
		if not self.terminated:
			yield self
		return self.product

	def exit_event_connect(self, processor, callback, dict=dict):
		"""
		# Connect the given callback to the exit of the given processor.
		# The &processor must be controlled by &self and any necessary
		# data structures will be initialized.
		"""

		assert processor.controller is self

		eec = self.exit_event_connections
		if eec is None:
			eec = self.exit_event_connections = dict()

		cbl = eec.get(processor, ())
		eec[processor] = cbl + (callback,)

	def exit_event_disconnect(self, processor, callback):
		"""
		# Remove the callback from the set of listeners.
		"""
		l = list(self.exit_event_connections[processor])
		l.remove(callback)
		if not l:
			del self.exit_event_connections[processor]
		else:
			self.exit_event_connections[processor] = tuple(l)

	def exit_event_emit(self, processor, partial=functools.partial):
		"""
		# Called when an exit occurs to emit exit events to any connected callbacks.
		"""

		eec = self.exit_event_connections
		if eec is not None:
			self.context.enqueue(*[partial(x, processor) for x in eec.pop(processor, ())])
			if not eec:
				del self.exit_event_connections

	def structure(self):
		"""
		# Provides the structure stack with at-exit callbacks.
		"""

		props = []
		sr = ()

		if self.exit_event_connections is not None:
			props.append(('exit_event_connections', self.exit_event_connections))

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
	interrupted = False

	def structure(self):
		p = ()

		sr = [
			(hex(id(x)), x)
			for x in itertools.chain.from_iterable(self.processors.values())
		]

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
			for Class, sset in list(self.processors.items()):
				for proc in sset:
					proc.subresource(self)
					proc.actuate()
					proc._pexe_state = 1
		except BaseException as exc:
			self.fault(exc)

		return super().actuate()

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

	def acquire(self, processor):
		"""
		# Add a process to the Sector; the processor is assumed to have been actuated.
		"""

		processor.subresource(self)
		self.processors[processor.__class__].add(processor)

	def process(self, events):
		"""
		# Load the sequence of &Processor instances into the Sector and actuate them.
		"""

		structs = self.processors

		for ps in events:
			ps.subresource(self)
			structs[ps.__class__].add(ps)
			ps.actuate()
			ps._pexe_state = 1

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
			self.ctx_enqueue_task(self.reap)

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
		# XXX: Replace .flow() or create a more stable access point. (implicit or explicit)
		self.process(series)

		x = series[0]
		for n in series[1:]:
			x.f_connect(n)
			x = n

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
			struct[x.__class__].discard(x)
			self.exit_event_emit(x)
			classes.add(x.__class__)

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
		now = libtime.now()
		items = list(self.state.schedule.items())
		pit = self.state.meter.snapshot()
		pit = now.__class__(pit)

		p = [
			('now', now.select('iso')),
		]

		p.extend([
			((pit.measure(ts)), callbacks)
			for ts, callbacks in items
		])

		return (p, sr)

	def actuate(self):
		self.state = libtime.Scheduler()
		self.persistent = True

		controller = self.controller

		if not isinstance(controller, Sector):
			# Controller is the Unit, so the execution context is used
			# to provide the scheduling primitives.
			self.x_ops = (
				self.context.defer,
				self.context.cancel
			)
		else:
			controller = controller.controller

			while controller is not None:
				if controller.scheduler is not None:
					sched = controller.scheduler
					break
				controller = controller.controller

			self.x_ops = (
				sched.defer,
				sched.cancel,
			)

	@staticmethod
	def execute_weak_method(weakmethod):
		return weakmethod()()

	def update(self):
		"""
		# Update the scheduled transition callback.
		"""

		nr = weakref.WeakMethod(self.transition)
		if self.scheduled_reference is not None:
			self.x_ops[1](self.scheduled_reference)

		sr = self.scheduled_reference = functools.partial(self.execute_weak_method, nr)
		self.x_ops[0](self.state.period(), sr)

	def schedule(self, pit:libtime.Timestamp, *tasks, now=libtime.now):
		"""
		# Schedule the &tasks to be executed at the specified Point In Time, &pit.
		"""

		measure = now().measure(pit)
		return self.defer(measure, *tasks)

	def defer(self, measure, *tasks):
		"""
		# Defer the execution of the given &tasks by the given &measure.
		"""

		p = self.state.period()

		self.state.put(*[
			(measure, x) for x in tasks
		])

		if p is None:
			self.update()
		else:
			np = self.state.period()
			if np < p:
				self.update()

	def cancel(self, task):
		"""
		# Cancel the execution of the given task scheduled by this instance.
		"""

		self.state.cancel(task)

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

		period = self.state.period
		get = self.state.get

		tasks = get()
		for task_objects in tasks:
			try:
				# Resolve weak reference.
				measure, scheduled_task = task_objects

				if scheduled_task is not None:
					scheduled_task()
			except BaseException as scheduled_task_exception:
				raise
				self.fault(scheduled_task_exception)
				break # don't re-schedule transition
		else:
			p = period()

			try:
				if p is not None:
					# re-schedule the transition
					self.update()
				else:
					# falls back to class attribute; None
					del self.scheduled_reference
			except BaseException as scheduling_exception:
				raise
				self.fault(scheduling_exception)

	def process(self, event, Point=libtime.core.Point, Measure=libtime.core.Measure):
		"""
		# Schedule the set of tasks.
		"""

		schedule = self.state.put
		p = self.state.period()

		for timing, task in event:
			if isinstance(timing, Point):
				measure = libtime.now().measure(timing)
			elif isinstance(timing, Measure):
				measure = timing
			else:
				raise ValueError("scheduler requires a libtime.Unit")

			schedule((measure, task))

		if p is None:
			self.update()
		else:
			np = self.state.period()
			if np < p:
				self.update()

	def interrupt(self):
		# cancel the transition callback
		if self.scheduled_reference is not None:
			self.x_ops[1](self.scheduled_reference)

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

		self.ctx_enqueue_task(self._recur_occur)

	def recur_execute(self):
		if self._recur_inhibit:
			return None

		try:
			return self.recur_target()
		except BaseException as exc:
			self.fault(exc)

	def _recur_occur(self):
		"""
		# Invoke a recurrence and use its return to schedule its next iteration.
		"""

		next_delay = self.recur_execute()

		if next_delay is None:
			if not self.interrupted:
				self.exit()
		else:
			self.controller.scheduler.defer(next_delay, self._recur_occur)

	def terminate(self, by=None):
		self._recur_inhibit = True
		self.exit()

	def interrupt(self):
		self._recur_inhibit = True

