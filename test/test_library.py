from .. import library
from .. import traffic

def test_transformer(test):
	class X(library.Transformer):
		def process(self, arg):
			pass

def test_empty_flow(test):
	f = library.Flow()
	#test/f.process('event') is None

def test_flow_obstructions(test):
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

def test_flow_operation(test):
	f = library.Flow()

	# base class transformers emit what they're given to process
	xf1 = library.Transformer()
	xf2 = library.Transformer()
	xf3 = library.Transformer()

	endpoint = []

	f.append('first', xf1)
	f.append('second', xf2)

	f.emit = endpoint.append

	f.process("event")

	test/endpoint == ["event"]

	# validate that the final transformer's endpoint is maintained
	f.append('third', xf3)
	f.process("event2")

	test/endpoint == ["event", "event2"]

def test_io(test):
	class Context(object):
		pass
	ctx = Context()

	f = library.IO()
	test/f.input != None
	test/f.output != None

if __name__ == '__main__':
	import sys; from ...development import libtest
	libtest.execute(sys.modules['__main__'])
