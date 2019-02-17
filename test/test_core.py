from .. import core

def test_Condition(test):
	Type = core.Condition

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
	inex = core.Inexorable
	test/bool(inex) == False
	test.isinstance(inex, core.Condition)

def test_Join(test):
	Type = core.Join

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

if __name__ == '__main__':
	import sys; from ...test import library as libtest
	libtest.execute(sys.modules['__main__'])
