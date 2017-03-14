import collections
import functools
import importlib.util
import typing
import itertools

from .. import library
from .. import libcommand

def test_parallel(test):
	t = False
	def nothing(*args):
		nonlocal t
		t = True

	i = functools.partial(libcommand.initialize, main=nothing)

	try:
		with library.parallel(i) as unit:
			pass
	except KeyError:
		# There's a race condition, atm, as
		# the Unit is terminating before it
		# is being selected from the index.
		# If there's a key error, rely on
		# subsequent test to validate success.
		pass
	test/t == True

class ExitController(object):
	"""
	Root controller for tests.
	"""
	def __init__(self):
		self.exits = []
		self.callbacks = collections.defaultdict(list)

	def exited(self, processor):
		self.exits.append(processor)

	def exit_event_connect(self, subject, cb):
		self.callbacks[subject].append(cb)

# used to emulate io.library.Context
class TContext(object):
	process = None

	def __init__(self):
		self.tasks = []
		self.faults = []

	def _sys_traffic_attach(self, *ignored):
		pass # Tests don't use real transits.

	def associate(self, processor):
		self.association = lambda: processor
		processor.context = self

	def enqueue(self, *tasks):
		self.tasks.extend(tasks)

	def faulted(self, resource):
		self.faults.append(resource)
		faultor = resource.controller
		faultor.interrupt()
		if faultor.controller:
			faultor.controller.exited(faultor)

	def __call__(self):
		l = len(self.tasks)
		e = self.tasks[:l]
		del self.tasks[:l]
		for x in e:
			x()

	def defer(self, mt):
		pass

	def cancel(self, task):
		pass

	def flush(self, maximum=128):
		i = 0
		while self.tasks:
			self()
			i += 1
			if i > maximum:
				raise Exception('exceeded maximum iterations for clear test context task queue')

class TTransit(object):
	link = None

	# for representation during debugging
	resource = None
	port = '<test transit>'
	def endpoint(self):
		return None

	def acquire(self, obj):
		self.resource = obj

	def subresource(self, obj):
		self.controller = obj

	def process(self, event):
		pass

	def inject(self, event):
		self.f_emit((event,))

	def k_transition(self):
		pass

def sector():
	"Construct a root Sector and Context for testing."
	ctx = TContext()
	sect = library.Sector()
	sect.context = ctx
	x = ExitController()
	sect.controller = x
	sect.actuate()
	return ctx, sect

def test_Lock(test):
	"""
	Check event driven mutual exclusion. Uses main thread access to synchronize.
	"""

	s = library.Lock()
	cell = []
	def inc(release):
		cell.append(1)
	def dec(release):
		cell.append(-1)

	s.acquire(inc)
	test/sum(cell) == 1
	s.acquire(dec)
	s.release()
	test/sum(cell) == 0

def test_Join(test):
	Type = library.Join

	class Exiting(object):
		product = None

		def atexit(self, cb):
			self.cb = cb

		def exit(self):
			self.cb(self)

	jp1 = Exiting()
	jp2 = Exiting()

	l = []
	j = Type(p1=jp1, p2=jp2)
	j.atexit(l.append)
	j.connect() # usually ran by the creator of the join

	jp1.exit()

	test/l == []
	jp2.exit() # last processor; run callback

	test/l == [j]
	test/j.callback == None # cleared
	j.atexit(l.append)
	test/l == [j, j]
	test/j.callback == None

	# validate that we can split the processors
	test/j['p1'] == jp1
	test/j['p2'] == jp2
	test/set(j) == {jp1, jp2}

def test_Transformer(test):
	class X(library.Transformer):
		def process(self, arg):
			pass

	x=X()

def test_Condition(test):
	Type = library.Condition

	class Root(object):
		@property
		def comparison(self):
			return self.a == self.b

		def parameter(self, ob):
			return ob == self.a

	R = Root()

	R.a = 1
	R.b = 2
	C = Type(R, ('comparison',))
	test/bool(C) == False

	R.a = 2
	test/bool(C) == True

	# deep attributes
	S = Root()
	R.sub = S
	C = Type(R, ('sub', 'comparison'))

	R.b = 3 # make sure we're not looking at S
	R.a = 0

	S.a = 10
	S.b = 10
	test/bool(C) == True

	# logical functions
	C = Type(R, ('sub', 'parameter'), 10)
	test/bool(C) == True

def test_Inexorable(test):
	inex = library.Inexorable
	test/bool(inex) == False
	test/inex / library.Condition

def test_FlowControl(test):
	"""
	Validate primitives.
	"""
	Type = library.FlowControl

	test/Type.initiate != Type.terminate
	test/Type.clear != Type.obstruct
	test/Type.initiate == Type.initiate

	test/str(Type.initiate) == 'initiate'
	test/repr(Type.initiate) == 'FlowControl.initiate'

	test/int(Type.initiate) == 2
	test/int(Type.transfer) == 0
	test/int(Type.terminate) == -2

def test_Flow_operation(test):
	# base class transformers emit what they're given to process
	xf1 = library.Reflection()
	xf2 = library.Reflection()
	xf3 = library.Reflection()

	endpoint = []
	def append(x, source=None):
		endpoint.append(x)

	f = library.Transformation(xf1, xf2, xf3)
	f.actuate()
	f.f_emit = append

	f.process("event")

	test/endpoint == ["event"]

	f.process("event2")

	test/endpoint == ["event", "event2"]

def test_Flow_obstructions(test):
	"Validate signaling of &library.Flow obstructions"

	status = []
	def obstructed(flow):
		status.append(True)

	def cleared(flow):
		status.append(False)

	f = library.Flow()
	f.f_watch(obstructed, cleared)

	f.f_obstruct(test, None)

	test/f.f_obstructed == True
	test/status == [True]

	f.f_obstruct(f, None)
	test/f.f_obstructed == True
	test/status == [True]

	f.f_clear(f)
	test/f.f_obstructed == True
	test/status == [True]

	f.f_clear(test)
	test/f.f_obstructed == False
	test/status == [True, False]

def test_Flow_obstructions_initial(test):
	"Validate obstruction signaling when obstruction is presented before the watch"

	status = []
	def obstructed(flow):
		status.append(True)

	def cleared(flow):
		status.append(False)

	f = library.Transformation(library.Reflection())
	f.f_obstruct(test, None)

	f.f_watch(obstructed, cleared)

	test/f.f_obstructed == True
	test/status == [True]

def test_Flow_obstructions(test):
	"Validate that joins receive obstruction notifications"

	l = []
	class ObstructionWatcher(library.Reactor):
		def suspend(self, flow):
			l.append('suspend')

		def resume(self, flow):
			l.append('resume')

	f = library.Transformation(ObstructionWatcher())
	f.actuate()

	f.f_obstruct(test, None)
	test/l == ['suspend']

	f.f_clear(test)
	test/l == ['suspend', 'resume']
	f.f_clear(test) # no op
	test/l == ['suspend', 'resume']

	f.f_obstruct(test, None)
	test/l == ['suspend', 'resume', 'suspend',]
	f.f_obstruct(test, None) # no op; already obstructed.
	test/l == ['suspend', 'resume', 'suspend',]

def setup_connected_flows():
	reservoir = []
	ctx = TContext()
	usector = library.Sector()
	usector.context = ctx
	usector.actuate()

	dsector = library.Sector()
	dsector.context = ctx
	dsector.actuate()

	us = library.Transformation(library.Reflection())
	ds = library.Transformation(library.Reflection())
	usector.dispatch(us)
	dsector.dispatch(ds)

	def append(event, source=None, end=reservoir):
		end.append((event, source))

	ds.f_emit = append
	return usector, dsector, reservoir, us, ds

def test_Flow_connect_events(test):
	"""
	Validate events of connected Flows across Sector boundaries.
	"""
	usector, dsector, reservoir, us, ds = setup_connected_flows()
	us.f_connect(ds)

	test/us.f_downstream is ds
	test/us.functioning == True
	test/ds.functioning == True
	us.process(1)
	test/reservoir == [(1, ds)]

	# validate that terminate is inherited
	us.terminate()
	test/us.terminated == True
	usector.context()
	test/ds.terminated == True

	usector, dsector, reservoir, us, ds = setup_connected_flows()
	us.f_connect(ds)

	# validate that interrupt is inherited
	us.interrupt()
	test/us.interrupted == True
	usector.context() # context is shared
	test/ds.interrupted == True

	# faulted flow
	usector, dsector, reservoir, us, ds = setup_connected_flows()
	us.f_connect(ds)

	# validate that interrupt is inherited
	us.fault(Exception("int"))
	usector.context() # context is shared
	test/us.interrupted == True
	test/ds.interrupted == True

	# The downstream should have had its exit signalled
	# which means the controlling sector should have
	# exited as well.
	dsector.context()
	test/dsector.terminated == True

def test_Iteration(test):
	c = library.Collection.list()
	e = ExitController()
	ctx = TContext()

	c.controller = e
	c.context = ctx
	c.actuate()

	i = library.Iteration(range(100))
	i.controller = e
	i.context = ctx
	i.f_connect(c)
	i.actuate()
	ctx.flush()

	test/c.c_storage == list(range(100))
	test/i.terminated == True

def test_null(test):
	e = ExitController()
	ctx = TContext()
	i = library.Iteration(range(100))
	i.controller = e
	i.context = ctx
	i.f_connect(library.null)
	i.actuate()
	ctx.flush()
	# Validate empty iterator.
	test/tuple(i.it_iterator) == ()

def test_Collection(test):
	"Similar to test_iterate, but install all storage types"

	ctx = TContext()
	exit = ExitController()

	c = library.Collection.dict()
	c.controller = exit
	c.context = ctx

	f = library.Flow()
	f.controller = exit
	f.context = ctx
	f.actuate()
	f.f_connect(c)

	events = [
		(1, "value1"),
		(2, "value2"),
		(3, "value3"),
		(2, "override"),
		("string-key", 0),
		("string-key", 1),
	]
	for x in events:
		f.process(x)

	test/c.c_storage == {1:"value1",2:"override",3:"value3","string-key":1}

	c = library.Collection.set()
	c.controller = exit
	c.context = ctx

	f = library.Flow()
	f.controller = exit
	f.context = ctx
	f.actuate()
	f.f_connect(c)

	events = [1, 2, 3, 3, 3, 4, 5]
	for x in events:
		f.process(x)

	test/sorted(list(c.c_storage)) == [1,2,3,4,5]

	b = library.Collection.buffer()
	b.actuate()
	b.process([b'data', b' ', b'more'])
	test/b.c_storage == b'data more'

def test_Functional(test):
	r = []

	ft = library.Functional(lambda x: x+1)
	ft.f_emit = r.append

	ft.process(1)
	ft.process(2)

	test/r == [2,3]

def test_Call(test):
	Type = library.Call
	ctx, sect = sector()

	arg = object()
	kw = object()

	effects = []
	def call_to_perform(arg1, key=None):
		effects.append(arg1)
		effects.append(key)
		effects.append(library.context().sector)
		effects.append('called')

	c = Type.partial(call_to_perform, arg, key=kw)
	sect.dispatch(c)

	ctx()

	test/effects[0] == arg
	test/effects[1] == kw
	test/effects[-1] == 'called'
	test/effects[-2] == sect

def test_Coroutine(test):
	"""
	Evaluate the functions of a &library.Coroutine process;
	notably the continuations and callback registration.
	"""
	Type = library.Coroutine
	ctx, sect = sector()
	return

	effects = []

	@typing.coroutine
	def coroutine_to_execute(sector):
		yield None
		effects.append(sector)
		effects.append('called')

	co = Type(coroutine_to_execute)
	sect.dispatch(co)
	ctx()

	test/effects[-1] == 'called'
	test/effects[0] == sect

def test_Allocator(test):
	ctx = TContext()
	t = TTransit()
	d = library.KernelPort(t)

	f = library.Transformation(*library.meter_input(d))
	f.context = ctx
	meter = f.xf_sequence[0]
	f.actuate()

	test/t.link == f.xf_sequence[1]
	test/meter.transferred == 0
	test/t.link == f.xf_sequence[1]
	f.xf_sequence[0].transition()
	fst_resource = t.resource

	test/meter.transferring == len(t.resource)
	rlen = len(t.resource)
	test/rlen > 0

	chunk = rlen // 2
	t.link.inject((t.resource[:chunk],))

	test/meter.transferred == chunk

	t.link.inject((t.resource[chunk:rlen-1],))
	test/meter.transferred == rlen-1

	test/meter.transferring == rlen

	t.link.inject((t.resource[rlen-1:],))
	test/meter.transferred == 0
	test/id(t.resource) != id(fst_resource)

def test_Throttle(test):
	ctx = TContext()
	t = TTransit()
	d = library.KernelPort(t)

	f = library.Transformation(*library.meter_output(d))
	f.context = ctx
	meter = f.xf_sequence[0]
	f.actuate()

	test/t.link == f.xf_sequence[1]
	test/meter.transferred == 0
	# nothing has been allocated
	test/meter.transferring == None

	f.process((b'datas',))
	fst_resource = t.resource

	test/meter.transferring == len(t.resource)
	rlen = len(t.resource)
	test/rlen > 0

	chunk = rlen // 2
	t.link.inject((t.resource[:chunk],))

	test/meter.transferred == chunk

	t.link.inject((t.resource[chunk:rlen-1],))
	test/meter.transferred == rlen-1

	test/meter.transferring == rlen

	f.process((b'following',))
	t.link.inject((t.resource[rlen-1:],))
	test/meter.transferred == 0
	test/id(t.resource) != id(fst_resource)

	# it appears desirable to test that the t.resource becomes None after
	# a full transfer, but that's testing the Transit's buffer exhaustion;
	# here, we're primarily interesting in successful rotations.

def test_Catenation(test):
	"""
	Flow sequencing tests.
	"""

	Type = library.Catenation
	fc_terminate = library.FlowControl.terminate
	fc_initiate = library.FlowControl.initiate
	fc_transfer = library.FlowControl.transfer
	ctx = TContext()

	S = library.Sector()
	S.context = ctx
	S.actuate()

	# output flow
	c = library.Collection.list()
	x = Type()
	S.dispatch(c)
	S.dispatch(x)
	x.f_connect(c)

	x_exit = []
	x.atexit(x_exit.append)
	# pair of inputs
	i1 = library.Iteration(range(0, -50, -1))
	i2 = library.Iteration(range(100))
	i3 = library.Iteration(range(100, 200, 2))

	list(map(S.acquire, (i1, i2, i3)))

	# reserve slots
	x.cat_reserve(1)
	x.cat_reserve(2)
	x.cat_connect(2, i2) # validate blocking of 1

	x.cat_reserve(3)
	i3.f_obstruct(test, None)

	# Data sent to the flow should be enqueued.
	# with test.annotate("enqueued flows do not emit")
	i2.actuate()
	ctx.flush()
	test/c.c_storage == []
	test/len(x.cat_connections[i2][0]) > 0
	test/i2.f_obstructed == True

	# connect fi, but don't transfer anything yet.
	x.cat_connect(1, i1)
	ctx.flush()
	test/c.c_storage[0] == [(fc_initiate, 1)]
	del c.c_storage[:]
	test/x.cat_connections[i1][0] == None # head of line shouldn't have queue.

	x.cat_connect(3, i3)
	i3.actuate()
	ctx.flush()
	test/c.c_storage == [] # i3 is not yet hol and...
	# i3 is obstructed prior to cat_connect; queue should be empty.
	test/list(x.cat_connections[i3][0]) == []

	test/i2.f_obstructed == True # Still obstructed by i1.
	# Check obstruction occurrence from enqueued transfers.
	obc = i2.f_obstructions[x][1]
	test/obc.focus == x
	test/obc.path == ('cat_overflowing',)

	i1.actuate()
	ctx.flush()
	test/i1.f_obstructed == False
	test/i1.terminated == True
	test/x.terminated == False
	test/x.terminating == False

	ctx.flush()
	test/i2.terminated == True
	test/i2.terminating == False
	test/i2.f_obstructed == False

	expect = list(zip(itertools.repeat(fc_transfer), itertools.repeat(1), range(0,-50,-1)))
	expect.append((fc_terminate, 1))
	expect.append((fc_initiate, 2))
	expect.extend(zip(itertools.repeat(fc_transfer), itertools.repeat(2), range(100)))
	expect.append((fc_terminate, 2))
	expect.append((fc_initiate, 3))

	test/list(itertools.chain.from_iterable(c.c_storage)) == expect
	test/i2.terminated == True
	del c.c_storage[:]

	test/x.terminated == False
	# termination completes when queue is empty.
	x.terminate(test)
	test/x.terminated == False
	test/x.terminating == True
	test/x.functioning == True

	# i3 was obstructed prior to cat_connect meaning, the queue
	# should be empty. It was connected after x.cat_connect(1, i1).
	test/x.cat_connections[i3][0] == None
	i3.f_clear(test)
	ctx.flush()
	expect = list(zip(itertools.repeat(fc_transfer), itertools.repeat(3), range(100, 200, 2)))
	expect.append((fc_terminate, 3))
	test/list(itertools.chain.from_iterable(c.c_storage)) == expect
	test/i3.terminated == True

	test/x.terminated == True
	test/x_exit == [x]

def test_Division(test):

	fc_xfer = library.FlowControl.transfer
	fc_terminate = library.FlowControl.terminate
	fc_init = library.FlowControl.initiate

	Type = library.Division
	Context = TContext()
	S = library.Sector()
	S.context = Context
	S.actuate()

	class Local(library.Mitre):
		accepted = []
		def process(self, requests, source=None):
			responses = self.f_emit(Layer() for x in requests)
			# received connection
			self.accepted.extend(requests)

	x = Type()
	mitre = Local()
	S.process((mitre, x))
	x.f_connect(mitre)

	# no content
	x.process([(fc_init, 1)])
	Context()
	test/mitre.accepted[0][0] == 1
	Context()

	test/mitre.accepted[0][1] / typing.Callable
	c = library.Collection.list()
	S.dispatch(c)
	x.process([(fc_xfer, 1, (b'data',))])
	x.div_connect(1, c)
	test/c.c_storage == [(b'data',)]
	test/c.terminated == False
	x.process([(fc_terminate, 1)])
	Context()
	test/c.terminated == True

if __name__ == '__main__':
	import sys; from ...development import libtest
	libtest.execute(sys.modules['__main__'])
