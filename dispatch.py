"""
# Executive processors.
"""
import os
import types
import collections
import functools
import typing
import errno
import signal

from . import core
from ..system import execution

class Call(core.Processor):
	"""
	# A single callable represented as a Processor.
	# Used as an abstraction for explicit enqueues, and to trigger faults in Sectors.

	# This should be rarely used in practice.
	"""

	def c_execution(self):
		self.c_returned = self.c_object() # Execute Callable.
		self.finish_termination()

	@classmethod
	def partial(Class, call:collections.abc.Callable, *args, **kw):
		"""
		# Create a call applying the arguments to the callable upon actuation.
		# The positional arguments will follow the &Sector instance passed as
		# the first argument.
		"""
		return Class(functools.partial(call, *args, **kw))

	def __init__(self, call:typing.Callable):
		"""
		# The partial application to the callable to perform.
		# Usually, instantiating from &partial is preferrable;
		# however, given the presence of a &functools.partial instance,
		# direct initialization is better.

		# [ Parameters ]
		# /call/
			# The callable to enqueue during actuation of the &Processor.
		"""
		self.c_returned = None
		self.c_object = call

	def actuate(self):
		self.critical(self.c_execution)

	def structure(self):
		return ([('c_object', self.c_object)], ())

	def terminate(self):
		# Ineffective.
		self.start_termination()

	def interrupt(self):
		self.interrupted = True

class Coroutine(core.Processor):
	"""
	# Processor for coroutines.

	# Manages the generator state in order to signal the containing &Sector of its
	# exit. Generator coroutines are the common method for serializing the dispatch of
	# work to relevant &Sector instances.

	# ! WARNING: Untested.
	"""

	def __init__(self, coroutine):
		self.source = coroutine

	@property
	def state(self):
		return self.unit.stacks[self]

	def _co_complete(self):
		super().terminate()
		self.controller.exited(self)

	def container(self):
		"""
		# ! INTERNAL: Private Method

		# Container for the coroutine's execution in order
		# to map completion to processor exit.
		"""
		try:
			yield None
			self.product = (yield from self.source)
			self.enqueue(self._co_complete)
		except BaseException as exc:
			self.product = None
			self.fault(exc)
	if hasattr(types, 'coroutine'):
		container = types.coroutine(container)

	def actuate(self, partial=functools.partial):
		"""
		# Start the coroutine.
		"""

		state = self.container()
		self.system.stacks[self] = state

		self.enqueue(state.send)

	def terminate(self):
		"""
		# Force the coroutine to close.
		"""
		if not super().terminate():
			return False
		self.state.close()
		return True

	def interrupt(self):
		self.state.throw(KeyboardInterrupt)
		self.interrupted = True

class Thread(core.Processor):
	"""
	# A &Processor that runs a callable in a dedicated thread.
	"""

	def __init__(self, callable):
		self.callable = callable

	def trap(self):
		final = None

		try:
			self.product = self.callable(self)
			self.start_termination()
			# Must be enqueued to exit.
			final = self.finish_termination
		except BaseException as exc:
			final = functools.partial(self.fault, exc)

		self.critical(final)

	def actuate(self):
		"""
		# Execute the dedicated thread for the transformer.
		"""

		self.system.execute(self, self.trap)

class Subprocess(core.Context):
	"""
	# A set of running system processes.
	# Terminates when all members of the set has exited *and* all subtransactions have completed.

	# [ Properties ]

	# /sp_reaper/
		# The callable used to collect the process status using the system process identifier.

	# /sp_exit_status/
		# A mapping of process identifiers to their corresponding exit status returned by
		# &sp_reaper after an exit event was received.

	# /sp_processes/
		# A mapping of process identifiers to user-defined objects used to identify
		# all the processes associated with the instance.

	# [ Engineering ]
	# While POSIX systems are the target platform, it's still preferrable to
	# abstract the concepts. Everything here dealing with signals should be
	# accessed through the system context.
	"""

	def __init__(self, reap, invocations:typing.Mapping[int,object]):
		self.sp_reaper = reap
		self.sp_processes = invocations
		self.sp_exit_status = {}

	def sp_report(self):
		"""
		# Join the System process identifier, invocation object, and exit status.
		"""
		for pid, status in self.sp_exit_status.items():
			yield pid, self.sp_processes[pid], status

	@classmethod
	def from_invocation(Class, invocation, stdout=None, stdin=None, stderr=None):
		"""
		# Instantiation from an &invocation executed with &invocation.spawn.
		# The process' standard I/O must be explicitly designated using
		# the &stdin, &stdout, and &stderr parameters.
		# Process will be reaped with &execution.reap.

		# [ Parameters ]
		# /invocation/
			# The &execution.KInvocation instance to spawn.
		# /stdin/
			# The file descriptor to map as standard input.
		# /stdout/
			# The file descriptor to map as standard output.
		# /stderr/
			# The file descriptor to map as standard error.
		"""

		fdmap = {}
		if stdin is not None:
			fdmap[0] = stdin
		if stdout is not None:
			fdmap[1] = stdout
		if stderr is not None:
			fdmap[2] = stderr

		pid = invocation.spawn(fdmap.items())
		return Class(execution.reap, {pid: invocation})

	def xact_void(self, last):
		if self.sp_reaped == True:
			self.finish_termination()

	def sp_exit(self, pid):
		# Target of the system event, this may be executed in cases
		# where the Processor has exited or was terminated.

		# Being that this is representation of a resource that is not
		# actually controlled by the Processor, it will continue
		# to update the state. However, the exit event will only
		# occur if the Sector is consistent.

		if not pid in self.sp_processes:
			raise RuntimeError("process identifier not in subprocess set")

		self.sp_exit_status[pid] = self.sp_reaper(pid)

		if len(self.sp_processes) == len(self.sp_exit_status) and not self.interrupted:
			# Don't exit if interrupted; maintain position in hierarchy.
			self.xact_exit_if_empty()

	def terminate(self):
		"""
		# If the process set isn't terminating, issue SIGTERM
		# to all of the currently running processes.
		"""

		if not self.terminating:
			self.start_termination()
			self.sp_signal(15)

	def structure(self):
		p = [
			x for x in [
				('sp_processes', self.sp_processes),
				('sp_exit_status', self.sp_exit_status),
			] if x[1]
		]
		return (p, ())

	def actuate(self):
		"""
		# Initialize the system event callbacks for receiving process exit events.
		"""

		self.system.connect_process_exit(self, self.sp_exit, *self.sp_processes)

	def interrupt(self, by=None, send_signal=os.kill):
		"""
		# Interrupt the running processes by issuing a SIGKILL signal to all active processes.
		# Exit status will be reaped, but not reported to &self.
		"""

		if self.interrupted:
			return False

		for pid in self.sp_waiting:
			try:
				send_signal(pid, 9)
			except ProcessLookupError:
				pass

		self.interrupted = True

	@property
	def sp_only(self):
		"""
		# The exit event of the only process in the set.
		# &None if no exit has occurred or the number of processes exceeds one.
		"""

		if len(self.sp_processes) > 1:
			return None

		for i in self.sp_exit_status.values():
			return i
		else:
			return None

	@property
	def sp_waiting(self) -> typing.Set[int]:
		"""
		# Return the set of process identifiers that have yet to exit.
		"""
		ps = set(self.sp_processes)
		ps.difference_update(self.sp_exit_status)
		return ps

	@property
	def sp_reaped(self) -> bool:
		"""
		# Whether all the processes have been reaped.
		"""
		return len(self.sp_processes) == len(self.sp_exit_status)

	def sp_signal(self, signo, send_signal=os.kill):
		"""
		# Send the given signal number (os.kill) to the active processes
		# being managed by the instance.
		"""

		for pid in self.sp_waiting:
			send_signal(pid, signo)

	def sp_signal_group(self, signo, send_signal=os.kill):
		"""
		# Send the given signal number (os.kill) to the active processes
		# being managed by the instance.
		"""

		for pid in self.sp_waiting:
			send_signal(-pid, signo)

	def sp_abort(self):
		"""
		# Interrupt the running processes by issuing a SIGQUIT signal.
		"""

		self.start_termination()
		self.sp_signal(signal.SIGQUIT)

class Coprocess(core.Context):
	"""
	# A local parallel process whose termination is connected to an instance.
	"""

	def __init__(self, identifier, application):
		self.cp_identifier = identifier
		self.cp_status = None
		self.cp_application = application
		self._cp_root_process = None

	def cp_process_exit(self, status=None):
		self.cp_status = status

		if not self.interrupted:
			self.xact_exit_if_empty()
		self._cp_root_process = None

	def cp_enqueue(self, task):
		self._cp_root_process.kernel.enqueue(task)

	def structure(self):
		p = [
			x for x in [
				('cp_status', self.cp_status),
			] if x[1]
		]
		return (p, ())

	def actuate(self):
		"""
		# Initialize the system event callbacks for receiving process exit events.
		"""

		self._cp_root_process = self.system.coprocess(
			self.cp_identifier, self.cp_process_exit,
			None, self.cp_application
		)

	def interrupt(self):
		"""
		# Interrupt the running processes by issuing a SIGKILL signal to all active processes.
		# Exit status will be reaped, but not reported to &self.
		"""

		if self.interrupted:
			return False

		try:
			xact = self._cp_root_process.transaction()
		except:
			# Process entry missing.
			pass
		else:
			xact.critical(xact.interrupt)

		self.interrupted = True

	def terminate(self):
		"""
		# Interrupt the running processes by issuing a SIGQUIT signal.
		"""

		if not self.functioning:
			return

		self.start_termination()
		xact = self._cp_root_process.transaction()
		self._cp_root_process.enqueue(xact.terminate)
