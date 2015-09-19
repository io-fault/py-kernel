import sys
from .. import libservice as library

system_extract_data = b"""<?xml version="1.0" encoding="utf-8"?>
<spawn xmlns="https://fault.io/xml/spawns" type="command" executable="/bin/cat">
 <documentation>Admin Information.</documentation>
 <requirements>
  <service name="NONE"/>
 </requirements>
 <environment>
  <setting name="ENV" value="VAL"/>
 </environment>
 <parameters>
  <field literal="-f"/>
  <field literal="some_file"/>
 </parameters>
</spawn>
"""

def test_extract(test):
	struct = library.extract(system_extract_data)
	test/struct['executable'] == "/bin/cat"
	test/struct['environment'] == {"ENV": "VAL"}
	test/struct['parameters'] == ["-f", "some_file"]
	test/struct['requirements'] == ["NONE"]
	test/struct['documentation'] == "Admin Information."
	test/struct['type'] == "command"

def test_construct(test):
	ix = library.extract(system_extract_data)
	i = library.construct(ix)
	x = library.extract(b''.join(i))
	test/x == ix

def test_service_routes(test):

	with library.routeslib.File.temporary() as tr:
		for i in range(12):
			sr = tr / ('s'+str(i))
			sr.init("directory")

		s = set(['s'+str(i) for i in range(12)])

		for bn, r in library.service_routes(tr):
			test/(bn in s) == True

def test_Service(test):

	with library.routeslib.File.temporary() as tr:
		# create, store/load and check empty

		srv = library.Service(tr, "test-service")
		libs = srv.libraries = [
			('foo', 'module.path.foo'),
		]

		srv.store()
		srv.load()

		test/srv.libraries == libs
		test/srv.enabled == False
		test/srv.parameters == []
		test/srv.requirements == []
		test/srv.environment == {}

		# modify and store, then create new service to compare
		enabled = srv.enabled = True
		params = srv.parameters = ['--foo', 'some', 'parameter']
		docs = srv.documentation = "SOME DOCUMENTATION"
		env = srv.environment = {"ENV1" : "VALUE1", "ENV2": "VALUE2"}
		exe = srv.executable = "/sbin/somed"

		srv.store()

		srv2 = library.Service(tr, "test-service")
		srv2.load()
		test/srv2.executable == exe
		test/srv2.environment == env
		test/srv2.documentation == docs
		test/srv2.parameters == params
		test/srv2.enabled == enabled
		test/srv2.enabled == True

		# check the alteration.
		srv.enabled = False
		srv.store_enabled()
		srv2.load_enabled()
		test/srv2.enabled == False

if __name__ == '__main__':
	import sys
	from ...development import libtest
	libtest.execute(sys.modules[__name__])
