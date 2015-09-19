import importlib.util
from .. import core as library

# used to emulate io.library.Context
class TContext(object):
	def __init__(self):
		self.tasks = []

	def associate(self, processor):
		self.association = lambda: processor
		processor.context = self

	def enqueue(self, task):
		self.tasks.append(task)

	def __call__(self):
		l = len(self.tasks)
		for x in self.tasks:
			x()
		del self.tasks[:l]

class TTransit(object):
	link = None

	def acquire(self, obj):
		self.resource = obj

	def subresource(self, obj):
		self.controller = obj

	def process(self, event):
		pass

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
	j = Type((jp1, jp2))
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
	f1, f2 = j
	test/f1 == jp1
	test/f2 == jp2

def test_ModuleSector(test):
	"Test the Library access interfaces."

	lmod = __package__ + '.ultest'
	mnf = __package__ + '.nomod'

	test/ImportError ^ (lambda: library.Library.from_fullname(mnf))

	u = library.Unit("none")
	ctx = TContext()
	ctx.associate(u)
	u.context = ctx
	test/ctx.association() == u
	u.actuate()

	ul = library.Library.from_fullname(lmod)
	u.place(ul, 'lib', 'test')
	ul.context = ctx
	ul.actuate()

	test/u.libraries / library.Libraries
	test/AttributeError ^ (lambda: u.libraries.nosuchlib)

	test/u.libraries.test / library.Library.Access
	test/AttributeError ^ (lambda: u.libraries.test.noattr)

	t = ul.api()

	test/t.func() == ul
	test/t.libs() == u.libraries
	test/t.libs().test == u.libraries.test

# r1, r2 = (yield lib.dns.somejoin(...)) 

def test_transformer(test):
	class X(library.Transformer):
		def process(self, arg):
			pass

	x=X()

def test_empty_flow(test):
	f = library.Flow()

	l = []
	def append(obj, source=None):
		l.append(obj)

	f.emit = append
	return
	f.process('event')
	#test/f.process('event') is None

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

def test_inexorable(test):
	inex = library.Inexorable
	test/bool(inex) == False
	test/inex / library.Condition

def test_flow_operation(test):
	f = library.Flow()

	# base class transformers emit what they're given to process
	xf1 = library.Transformer()
	xf2 = library.Transformer()
	xf3 = library.Transformer()

	endpoint = []
	def append(x, source=None):
		endpoint.append(x)

	f.affix(xf1, xf2, xf3)
	f.emit = append

	f.process("event")

	test/endpoint == ["event"]

	f.process("event2")

	test/endpoint == ["event", "event2"]

def test_flow_obstructions(test):
	"Validate signaling of &core.Flow obstructions"

	status = []
	def obstructed(flow):
		status.append(True)

	def cleared(flow):
		status.append(False)

	f = library.Flow()
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

def test_flow_obstructions_initial(test):
	"Validate obstruction signaling when obstruction is presented before the watch"

	status = []
	def obstructed(flow):
		status.append(True)

	def cleared(flow):
		status.append(False)

	f = library.Flow()
	f.obstruct(test, None)

	f.watch(obstructed, cleared)

	test/f.obstructed == True
	test/status == [True]

def test_join_obstructions(test):
	"Validate that joins receive obstruction notifications"

	l = []
	class ObstructionWatcher(library.Reactor):
		def suspend(self, flow):
			l.append('suspend')

		def resume(self, flow):
			l.append('resume')

	f = library.Flow()
	f.affix(ObstructionWatcher())

	f.obstruct(test, None)
	test/l == ['suspend']

	f.clear(test)
	test/l == ['suspend', 'resume']
	f.clear(test) # no op
	test/l == ['suspend', 'resume']

	f.obstruct(test, None)
	test/l == ['suspend', 'resume', 'suspend',]
	f.obstruct(test, None) # no op
	test/l == ['suspend', 'resume', 'suspend',]

def test_iterate(test):
	"Use the Collection Transformer to validate the iterator's functionality"

	c = library.Collect.list()
	i = library.Iterate()
	f = library.Flow()
	f.affix(i, c)

	f.process(range(100))
	test/c.storage == list(range(100))

def test_collect(test):
	"Similar to test_iterate, but install all storage types"

	c = library.Collect.dict()
	i = library.Iterate()
	f = library.Flow()
	f.affix(i, c)

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
	f = library.Flow()
	f.affix(i, c)

	f.process([
		1, 2, 3, 3, 3, 4, 5
	])

	test/sorted(list(c.storage)) == [1,2,3,4,5]

def test_allocator(test):
	t = TTransit()

	f = library.Flow()
	f.affix(*library.meter_input(t))
	meter = f.sequence[0]

	test/t.link == f.sequence[1]
	test/meter.transferred == 0

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

def test_throttle(test):
	t = TTransit()

	f = library.Flow()
	f.affix(*library.meter_output(t))
	meter = f.sequence[0]

	test/t.link == f.sequence[1]
	test/meter.transferred == 0
	test/meter.transferring == 0

	f.process(b'foobar')
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

	f.process(b'following')
	t.link.inject(t.resource[rlen-1:])
	test/meter.transferred == 0
	test/id(t.resource) != id(fst_resource)

	# it appears desirable to test that the t.resource becomes None after
	# a full transfer, but that's testing the Transit's buffer exhaustion;
	# here, we're primarily interesting in successful rotations.

def test_Serialize(test):
	""

	Type = library.Serialize

	def state_generator(layer, transport):
		transport(('start', layer))
		try:
			while True:
				transport((yield))
		finally:
			transport(('stop', layer))

	# output flow
	f = library.Flow()
	c = library.Collect.list()
	f.affix(c)

	# pair of inputs
	fi = library.Flow()
	i = library.Iterate()
	fi.affix(i)

	fib = library.Flow()
	i2 = library.Iterate()
	fib.affix(i2)

	fic = library.Flow()
	i3 = library.Iterate()
	fic.affix(i3)

	qs = Type(state_generator)
	qs.affix(f)

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
	test/c.storage == [('start', 1)] # init message

	c.storage.clear()
	fi.process(range(0, -50, -1))
	test/c.storage == list(range(0,-50,-1))

	# check that obstruction
	# with test.annotate("flow obstruction inheritance"):
	fi.obstruct(test, None, None)
	test/f.obstructed == True

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
	fi.obstruct(test, None, library.Inexorable)
	test/c.storage == [('stop', 1), ('start', 2)] + list(range(100))

	del c.storage[:]
	fib.obstruct(test, None, library.Inexorable)
	test/c.storage == [('stop', 2)]
	del c.storage[:]

	# fic still not connected
	test/c.storage == []
	qs.connect(3, fic)
	fic.clear(test)
	fic.obstruct(test, None, library.Inexorable)
	test/c.storage == [('start', 3)] + list(range(0, -10, -1)) + [('stop', 3)]

def test_Distribute(test):
	""

	closed = []
	accepted = []

	class Local(library.Resource):
		def close(self, *args):
			# layer [connection] closed
			closed.append(args)

		def accept(self, *args):
			# received connection
			accepted.append(args)

	root = Local()

	Type = library.Distribute
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

	d = Type(Layer, stateg, root.accept, root.close)
	d.subresource(root)
	test/d.controller == root

	# no content
	d.process(1) # init
	test/accepted == [(Layer.from_id(1),)]
	d.process(('end', None))
	test/closed == [(Layer.from_id(1),)]

	Layer.content = True
	d.process(2)
	l = accepted[1][0]

	f = library.Flow()
	f.subresource(root)
	c = library.Collect.list()
	f.affix(c)

	# queue content
	d.process('queued')
	d.connect(l, f)
	d.process('payload')
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

def test_Coroutine(self):
	"""
	Evaluate the functions of a &library.Coroutine process;
	notably the continuations and callback registration.
	"""

	Type = library.Coroutine
	output = []

	root = library.Sector()
	sect = library.Sector()
	access = None

	ctx = root.context = sect.context = TContext()
	root.dispatch(sect)

	def immediate(sector):
		yield None
		# started
		# requires explicit signal
		yield None

	def primary(coroutine):
		nonlocal access

		ico = Type.from_callable(immediate)
		sect.dispatch(ico)
		access = ico

		yield ico
		output.append('yield exited')

	co = Type.from_callable(primary)
	sect.dispatch(co)
	access.process(None)
	access.process(None)
	ctx()

	# test that immediate's atexit caused primary to continue
	test/output == ['yield exited']

if __name__ == '__main__':
	import sys; from ...development import libtest
	libtest.execute(sys.modules['__main__'])
