import typing
import importlib.util
from .. import core as library

class ExitController(object):
	"Provides a root controller for tests."
	def __init__(self):
		self.exits = []

	def exited(self, processor):
		self.exits.append(processor)

# used to emulate io.library.Context
class TContext(object):
	process = None

	def __init__(self):
		self.tasks = []
		self.faults = []

	def attach(self, *ignored):
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

def sector():
	"Construct a root Sector and Context for testing."
	ctx = TContext()
	sect = library.Sector()
	sect.context = ctx
	x = ExitController()
	sect.controller = x
	sect.actuate()
	return ctx, sect

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

# r1, r2 = (yield lib.dns.somejoin(...)) 

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

def test_Flow_operation(test):
	# base class transformers emit what they're given to process
	xf1 = library.Reflection()
	xf2 = library.Reflection()
	xf3 = library.Reflection()

	endpoint = []
	def append(x, source=None):
		endpoint.append(x)

	f = library.Flow(xf1, xf2, xf3)
	f.emit = append

	f.process("event")

	test/endpoint == ["event"]

	f.process("event2")

	test/endpoint == ["event", "event2"]

def test_Flow_obstructions(test):
	"Validate signaling of &core.Flow obstructions"

	status = []
	def obstructed(flow):
		status.append(True)

	def cleared(flow):
		status.append(False)

	f = library.Flow(library.Reflection())
	f.watch(obstructed, cleared)

	f.obstruct(test, None)

	test/f.obstructed == True
	test/status == [True]

	f.obstruct(f, None)
	test/f.obstructed == True
	test/status == [True]

	f.clear(f)
	test/f.obstructed == True
	test/status == [True]

	f.clear(test)
	test/f.obstructed == False
	test/status == [True, False]

def test_Flow_obstructions_initial(test):
	"Validate obstruction signaling when obstruction is presented before the watch"

	status = []
	def obstructed(flow):
		status.append(True)

	def cleared(flow):
		status.append(False)

	f = library.Flow(library.Reflection())
	f.obstruct(test, None)

	f.watch(obstructed, cleared)

	test/f.obstructed == True
	test/status == [True]

def test_Flow_obstructions(test):
	"Validate that joins receive obstruction notifications"

	l = []
	class ObstructionWatcher(library.Reactor):
		def suspend(self, flow):
			l.append('suspend')

		def resume(self, flow):
			l.append('resume')

	f = library.Flow(ObstructionWatcher())

	f.obstruct(test, None)
	test/l == ['suspend']

	f.clear(test)
	test/l == ['suspend', 'resume']
	f.clear(test) # no op
	test/l == ['suspend', 'resume']

	f.obstruct(test, None)
	test/l == ['suspend', 'resume', 'suspend',]
	f.obstruct(test, None) # no op; already obstructed.
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

	us = library.Flow(library.Reflection())
	ds = library.Flow(library.Reflection())
	usector.dispatch(us)
	dsector.dispatch(ds)

	def append(event, source=None, end=reservoir):
		end.append((event, source))

	ds.emit = append
	return usector, dsector, reservoir, us, ds

def test_Flow_connect_events(test):
	"""
	Validate events of connected Flows across Sector boundaries.
	"""
	usector, dsector, reservoir, us, ds = setup_connected_flows()
	us.connect(ds)

	test/us.downstream is ds
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
	us.connect(ds)

	# validate that interrupt is inherited
	us.interrupt()
	test/us.interrupted == True
	usector.context() # context is shared
	test/ds.interrupted == True

	# faulted flow
	usector, dsector, reservoir, us, ds = setup_connected_flows()
	us.connect(ds)

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

def test_Iterate(test):
	"Use the Collection Transformer to validate the iterator's functionality"

	c = library.Collect.list()
	i = library.Iterate()
	e = ExitController()
	f = library.Flow(i, c)
	f.controller = e
	f.actuate()

	f.process(range(100))
	test/c.storage == list(range(100))
	test/f.obstructed == True

	f.process(range(100, -1, -1))
	test/c.storage == (list(range(100)) + list(range(100, -1, -1)))

	# trigger terminal
	i.terminal = True
	f.process(())
	test/f.terminated == True
	test/e.exits << f

	i = library.Iterate(terminal=True)
	test/i.terminal == True

def test_Collect(test):
	"Similar to test_iterate, but install all storage types"

	c = library.Collect.dict()
	i = library.Iterate()
	f = library.Flow(i, c)
	f.actuate()

	f.process([
		(1, "value1"),
		(2, "value2"),
		(3, "value3"),
		(2, "override"),
		("string-key", 0),
		("string-key", 1),
	])

	test/c.storage == {1:"value1",2:"override",3:"value3","string-key":1}

	c = library.Collect.set()
	i = library.Iterate()
	f = library.Flow(i, c)
	f.actuate()

	f.process([
		1, 2, 3, 3, 3, 4, 5
	])

	test/sorted(list(c.storage)) == [1,2,3,4,5]

def test_Call(test):
	Type = library.Call
	ctx, sect = sector()

	arg = object()
	kw = object()

	effects = []
	def call_to_perform(sector, arg1, key=None):
		effects.append(arg1)
		effects.append(key)
		effects.append(sector)
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

	f = library.Flow(*library.meter_input(d))
	f.context = ctx
	meter = f.sequence[0]
	f.actuate()

	test/t.link == f.sequence[1]
	test/meter.transferred == 0
	test/t.link == f.sequence[1]
	f.sequence[0].transition()
	fst_resource = t.resource

	test/meter.transferring == len(t.resource)
	rlen = len(t.resource)
	test/rlen > 0

	chunk = rlen // 2
	t.link.inject(t.resource[:chunk])

	test/meter.transferred == chunk

	t.link.inject(t.resource[chunk:rlen-1])
	test/meter.transferred == rlen-1

	test/meter.transferring == rlen

	t.link.inject(t.resource[rlen-1:])
	test/meter.transferred == 0
	test/id(t.resource) != id(fst_resource)

def test_Throttle(test):
	ctx = TContext()
	t = TTransit()
	d = library.KernelPort(t)

	f = library.Flow(*library.meter_output(d))
	f.context = ctx
	meter = f.sequence[0]
	f.actuate()

	test/t.link == f.sequence[1]
	test/meter.transferred == 0
	# nothing has been allocated
	test/meter.transferring == None

	f.process((b'datas',))
	fst_resource = t.resource

	test/meter.transferring == len(t.resource)
	rlen = len(t.resource)
	test/rlen > 0

	chunk = rlen // 2
	t.link.inject(t.resource[:chunk])

	test/meter.transferred == chunk

	t.link.inject(t.resource[chunk:rlen-1])
	test/meter.transferred == rlen-1

	test/meter.transferring == rlen

	f.process((b'following',))
	t.link.inject(t.resource[rlen-1:])
	test/meter.transferred == 0
	test/id(t.resource) != id(fst_resource)

	# it appears desirable to test that the t.resource becomes None after
	# a full transfer, but that's testing the Transit's buffer exhaustion;
	# here, we're primarily interesting in successful rotations.

def test_Sequencing(test):

	Type = library.Sequencing
	Context = TContext()

	def state_generator(layer, transport):
		transport(('start', layer))
		try:
			while True:
				transport((yield))
		finally:
			transport(('stop', layer))

	S = library.Sector()
	S.context = Context

	# output flow
	c = library.Collect.list()
	f = library.Flow(c)

	# pair of inputs
	i = library.Iterate()
	fi = library.Flow(i)

	i2 = library.Iterate()
	fib = library.Flow(i2)

	i3 = library.Iterate()
	fic = library.Flow(i3)

	S.actuate()
	S.process((f, fi, fib, fic))

	qs = Type(state_generator)
	qs.requisite(f) # output flow

	# reserve slots
	qs.enqueue(1)
	qs.enqueue(2)
	qs.connect(2, fib) # validate blocking of 1

	qs.enqueue(3)

	fic.obstruct(test, None)

	# Data sent to the flow should be enqueued.
	# with test.annotate("enqueued flows do not emit")
	fib.process(range(100))
	test/c.storage == []

	# connect fi, but don't transfer anything
	qs.connect(1, fi)

	fic.process(range(0,-10,-1))

	# init message from qs.connect(1, fi)
	test/c.storage == [('start', 1)]

	c.storage.clear()
	fi.process(range(0, -50, -1))
	test/c.storage == list(range(0,-50,-1))

	# check that obstruction
	# with test.annotate("flow obstruction inheritance"):
	fi.obstruct(test, None, None)
	test/f.obstructed == True # because fi is obstructed

	del c.storage[:]
	test/c.storage == []

	# it's obstructed, but transfers still happen
	# relying on the buffering of the target flow
	# with test.annotate("head of line still flows with obstruction")
	fi.sequence[0].inject(0)
	fi.sequence[0].inject(1)
	fi.sequence[0].inject(-1)
	test/c.storage == [0, 1, -1]

	del c.storage[:]

	fi.clear(test)
	# with test.annotate("pop head of line and check effect")
	fi.terminate()

	Context() # run queue to cause transition from fi's termination.
	Context()
	test/c.storage == [('stop', 1), ('start', 2)] + list(range(100))

	del c.storage[:]
	fib.terminate()
	Context()
	Context()
	test/c.storage == [('stop', 2)]
	del c.storage[:]

	# fic is still not connected, so connect should identify it as the front.
	test/c.storage == []
	qs.connect(3, fic)
	fic.clear(test)
	fic.terminate()
	test/c.storage == [('start', 3)] + list(range(0, -10, -1))
	Context()
	Context()
	test/c.storage == [('start', 3)] + list(range(0, -10, -1)) + [('stop', 3)]

def test_Distributing(test):

	Context = TContext()
	accepted = []

	class Local(library.Resource):
		def accept(self, *args):
			# received connection
			accepted.append(args[1:])

	root = Local()
	root.context = Context

	Type = library.Distributing
	class Layer(library.Layer):
		content = None

		def __init__(self):
			self.id = None

		def __eq__(self, ob):
			return ob.id == self.id

		def __hash__(self):
			return id(self)

		@classmethod
		def from_id(Class, id):
			r = Class()
			r.id = id
			return r

	def stateg(allocate, start, transport, finish):
		while True:
			init = (yield)
			ctx = allocate()
			ctx.id = init
			start(ctx)
			r = (yield)

			while r != ('end', None):
				transport(ctx, r)
				r = (yield)

			finish(ctx)

	d = Type(Layer, root.accept)
	d.subresource(root)
	test/d.controller == root

	dentry = stateg(Layer, d.accept, d.transport, d.close)
	next(dentry)

	# no content
	dentry.send(1) # init
	Context()
	test/accepted == [(Layer.from_id(1),None)]
	dentry.send(('end', None))
	Context()

	Layer.content = True
	dentry.send(2)
	Context()
	l = accepted[1][0]

	c = library.Collect.list()
	f = library.Flow(c)
	f.subresource(root)

	# queue content
	dentry.send('queued')
	Context()
	d.connect(l, f)
	dentry.send('payload')
	Context()
	test/c.storage == ['queued', 'payload']

	# glass box; make sure the state is anticipated
	test/d.queues.get(l) == None # connected to flow
	test/d.flows.get(l) != None # has flow

	# two requests
	# first becomes fully queued
	# begins second into a an actual flow

	del c.storage[:]

def test_QueueProtocol(test):
	"""
	Test the &library.QueueProtocol processor.
	"""

	Type = library.QueueProtocol

	# queue protocol
	pass

def test_Composition(test):
	effect = []

	C = library.Composition()
	C.actuate()
	def add(x):
		return x+1

	C.emit = effect.append
	C.process(None)
	test/effect[-1] == None

	C.compose(add, add, add)
	C.process(1)
	test/effect[-1] == 4

	C.compose(add, add)
	C.process(1)
	test/effect[-1] == 3

	C.compose(add)
	C.process(1)
	test/effect[-1] == 2

	C.compose()
	C.process(1)
	test/effect[-1] == 1

if __name__ == '__main__':
	import sys; from ...development import libtest
	libtest.execute(sys.modules['__main__'])
